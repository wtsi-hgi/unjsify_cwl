import argparse
import copy
import itertools
import json
import os
import os.path as path
import re
import shutil
import sys
from typing import Any, Dict
import types
import tempfile
import logging
from cwltool.load_tool import fetch_document, validate_document, resolve_tool_uri

import pkg_resources
import ruamel.yaml as yaml

from .get_expressions import scan_expression, is_parameter_reference


def dict_map(func, d):
    return dict([func(key, value) for key, value in d.items()])

EXPR_SYMBOL = "__exprs"
OUTPUT_EXPR_SYMBOL = "__output_exprs"

logger = logging.getLogger()

def get_cwl_map(cwl_map, name, id_token="id"):
    if isinstance(cwl_map, dict):
        return cwl_map.get(name)
    else:
        for element in cwl_map:
            if element[id_token] == name:
                return element

def set_cwl_map(cwl_map, name, value, id_token="id"):
    if isinstance(cwl_map, dict):
        cwl_map[name] = value
    else:
        for i, element in enumerate(cwl_map):
            if element[id_token] == name:
                cwl_map[i] = value

def remove_cwl_map(cwl_map, name, id_token="id"):
    if isinstance(cwl_map, dict):
        del cwl_map[name]
    else:
        for element in cwl_map:
            if element[id_token] == name:
                cwl_map.remove(element)

def add_cwl_map(cwl_map, name, id_token="id", object=None):
    if object is None:
        object = {}

    if isinstance(cwl_map, dict):
        cwl_map[name] = object
    else:
        object[id_token] = name

        cwl_map.append(object)

    return object

def get_map_keys(cwl_map, id_token="id"):
    if isinstance(cwl_map, dict):
        return list(cwl_map.keys())
    else:
        return list(map(lambda x: x[id_token], cwl_map))

def map_to_array(cwl_map, id_token="id", secondary_symbol="source"):
    def to_dict(x):
        if not isinstance(x, dict):
            return {secondary_symbol: x}
        return x

    if isinstance(cwl_map, dict):
        return list(map(lambda key: update_dict(to_dict(cwl_map[key]), (id_token, key)), cwl_map.keys()))
    else:
        return cwl_map

def is_path_in(test_path, containing_path):
    return path.commonpath([path.abspath(test_path), path.abspath(containing_path)]) == path.abspath(containing_path)

def unjsify(workflow_location: str, outdir: str, base_cwldir: str):
    if not path.isdir(outdir):
        os.mkdir(outdir)

    with open(path.join(outdir, "eval_exprs.cwl"), "wb+") as eval_exprs_dest:
        with pkg_resources.resource_stream(__name__, "eval_exprs.cwl") as eval_exprs_source:
            shutil.copyfileobj(eval_exprs_source, eval_exprs_dest)

    return unjsify_workflow(workflow_location, outdir, base_cwldir)


def update_dict(d: dict, new_values):
    d.update(new_values)
    return d

def frozon(json_ob):
    if isinstance(json_ob, list):
        new_list = []
        for element in json_ob:
            new_list.append(frozon(element))

        return tuple(new_list)
    elif isinstance(json_ob, dict):
        new_dict = {}
        for key in json_ob:
            new_dict[key] = frozon(json_ob[key])

        return types.MappingProxyType(new_dict)
    else:
        return json_ob

cwl_file_cache = {} # type: Dict[str, Any]

def get_cwl(cwl_path):
    global cwl_file_cache
    # if cwl_path[:5] != "file:":
    #     cwl_path = f"file://{path.abspath(cwl_path)}"

    # document_loader, workflowobj, uri = fetch_document(cwl_path)
    # document_loader, _, _, _, _ = validate_document(document_loader, workflowobj, uri, strict=False, preprocess_only=True)
    # return document_loader.resolve_ref(uri)[0]

    hash_pos = cwl_path.find("#")

    if hash_pos != -1:
        hash_part = cwl_path[hash_pos+1:]
        cwl_path = cwl_path[:hash_pos]

    if cwl_file_cache.get(cwl_path) is not None:
        cwl = cwl_file_cache[cwl_path]
    else:
        with open(cwl_path) as fp:
            cwl = yaml.load(fp, Loader=yaml.Loader)

        cwl_file_cache[cwl_path] = cwl

    if hash_pos != -1:
        return get_cwl_map(cwl["$graph"], hash_part)

    return cwl

def resolve_path(current_workflow, path_to_resolve):
    if path_to_resolve[0] == "#":
        curr_hash = current_workflow.find("#")

        new_path = current_workflow[:curr_hash] + path_to_resolve
    else:
        if not path.isabs(path_to_resolve):
            new_path = path.join(path.dirname(current_workflow), path_to_resolve)
        else:
            new_path = path_to_resolve

    return new_path

def iterate(func):
    while True:
        yield func()

def get_identity_workflow(steps_names):
    return {
        "class": "Workflow",
        "inputs": dict(zip(steps_names, iterate(lambda: {"type": "Any?"}))),
        "outputs":  dict(map(lambda x: (x, {
            "type": "Any?",
            "outputSource": x
        }), steps_names)),
        "steps": []
    }

JSONType = Dict[str, Any]

def unjsify_workflow(workflow_location: str, outdir: str, base_cwldir: str):
    def write_new_cwl(old_location, cwl):
        if not is_path_in(old_location, base_cwldir):
            raise Exception(f"Invalid reference to file {old_location}, outside the basedir of {base_cwldir}")

        hash_pos = old_location.find("#")

        if hash_pos != -1:
            hash_part = old_location[hash_pos+1:]
            base_cwl = get_cwl(old_location[:hash_pos])

            set_cwl_map(base_cwl["$graph"], hash_part, cwl)
            cwl = base_cwl

        out_file = path.join(outdir, path.relpath(old_location, base_cwldir))

        os.makedirs(path.dirname(out_file), exist_ok=True)

        with open(out_file, "w") as output_file:
            yaml.dump(cwl, output_file, default_flow_style=False)
    workflow_cwl = get_cwl(workflow_location)

    if workflow_cwl["class"] != "Workflow":
        workflow_cwl = {
            "cwlVersion": "v1.0",
            "class": "Workflow",
            "inputs": dict(zip(get_map_keys(workflow_cwl["inputs"], "id"), iterate(lambda: {"type": "Any?"}))),
            "outputs": dict(map(lambda x: (x, {"outputSource": "cmdline_tool/" + x, "type": "Any?"}),
                get_map_keys(workflow_cwl["outputs"], "id"))),
            "requirements": [{
                "class": "SubworkflowFeatureRequirement"
            }],
            "steps": [{
                "id": "cmdline_tool",
                "run": "__" + path.basename(workflow_location),
                "in": dict(zip(get_map_keys(workflow_cwl["inputs"], "id"), get_map_keys(workflow_cwl["inputs"], "id"))),
                "out": list(get_map_keys(workflow_cwl["outputs"], "id"))
            }]
        }

        global cwl_file_cache
        cwl_file_cache[resolve_path(workflow_location, "__" + path.basename(workflow_location))] = get_cwl(workflow_location)

    if get_cwl_map(workflow_cwl["requirements"], "InlineJavascriptRequirement", "class") is not None:
        workflow_expression_lib = get_cwl_map(workflow_cwl["requirements"], "InlineJavascriptRequirement", "class").get("expressionLib", {})
        remove_cwl_map(workflow_cwl["requirements"], "InlineJavascriptRequirement", "class")

    new_workflow_cwl = copy.deepcopy(workflow_cwl)

    if "requirements" not in new_workflow_cwl:
        new_workflow_cwl["requirements"] = []

    # this is needed to pass multiple inputs to the expression evaluation step
    add_cwl_map(new_workflow_cwl["requirements"], "MultipleInputFeatureRequirement", "class")

    eval_exprs_location = path.relpath(path.join(base_cwldir, "eval_exprs.cwl"), path.dirname(workflow_location))

    for i, step in enumerate(workflow_cwl["steps"]):
        if isinstance(step, str):
            step_id = step
            step = workflow_cwl["steps"][step]
        else:
            step_id = step["id"]
        step_run_location = resolve_path(workflow_location, step["run"])

        step_cwl = get_cwl(step_run_location)

        #### Init steps
        workflow_expr_step = {} # type: JSONType
        workflow_expr_process_step = {} # type: JSONType
        runtime_expr_step = {} # type: JSONType
        inputs_expr_step = {} # type: JSONType
        output_processing_step = {} # type: JSONType

        workflow_expr_new_valuesFrom = {}
        workflow_exprs = []
        for step_in in map_to_array(step["in"]):
            if isinstance(step_in, dict):

                def on_found_workflow_expr(expression):
                    workflow_exprs.append({"self": f"inputs.{step_in}", "expr": expression})
                    return f"$(inputs.{OUTPUT_EXPR_SYMBOL}[{len(workflow_exprs) - 1}])"

                if step_in.get("valueFrom") is not None:
                    new_valueFrom = replace_expr(step_in["valueFrom"], on_found_workflow_expr)

                    workflow_expr_new_valuesFrom[step_in["id"]] = new_valueFrom

        if workflow_exprs != []:
            if workflow_expression_lib == "":
                workflow_expression_lib_dict_pair = []
            else:
                workflow_expression_lib_dict_pair = [("expressionLib", {"default": ";".join(workflow_expression_lib)})]

            workflow_expr_step = {
                "id": "__process_workflow_exprs",
                "run": eval_exprs_location,
                "in": update_dict(
                    {
                        "input_values": {
                            "source": list(step["in"].keys())
                        },
                        "input_names": {
                            "default": list(step["in"].keys())
                        },
                        "expressions": {
                            "default": workflow_exprs
                        }
                    },
                    workflow_expression_lib_dict_pair
                ),
                "out": ["output"]
            }

            workflow_expr_process_step = get_identity_workflow(
                list(workflow_expr_new_valuesFrom.keys())
            )

            for key, new_valueFrom in workflow_expr_new_valuesFrom.items():
                workflow_expr_process_step["requirements"] = {"StepInputExpressionRequirement": {}}
                workflow_expr_process_step["inputs"][key]["valueFrom"] = new_valueFrom


        if step_cwl["class"] == "CommandLineTool":
            js_req = get_cwl_map(step_cwl.get("requirements", []), "InlineJavascriptRequirement", "class")

            if js_req is not None:
                input_expressions, output_expressions, data_by_outputId, new_tool = unjsify_tool(step_cwl)
                write_new_cwl(step_run_location, new_tool)

                def get_output_from_name(output_name):
                    if data_by_outputId.get(output_name) is not None:
                        return (output_name, {
                            "outputSource": '__output_eval_exprs/output',
                            "outputBinding": {
                                "outputEval": data_by_outputId[output_name]["outputEval"]
                            },
                            "type": data_by_outputId[output_name]["type"]
                        })
                    return (output_name, {
                        "type": "Any",
                        "outputSource": f'{step_id}/{output_name}'
                    })

                if js_req.get("expressionLib") is None:
                    expression_lib_dict_pair = []
                else:
                    expression_lib_dict_pair = [("expressionLib", {"default": ";".join(js_req["expressionLib"])})]

                inputs_expr_step = {
                    "id": "__eval_input_exprs",
                    "run": eval_exprs_location,
                    "in": update_dict(
                        {
                            "input_values": {
                                "source": list(step["in"].keys())
                            },
                            "input_names": {
                                "default": list(step["in"].keys())
                            },
                            "expressions": {
                                "default": input_expressions
                            }
                        },
                        expression_lib_dict_pair
                    ),
                    "out": ["output"]
                }

                if output_expressions == []:
                    output_processing_step = {
                        "id": "__output_eval_exprs",
                        "run": eval_exprs_location,
                        "in": update_dict(
                            {
                                "input_values": {
                                    "source": list(map(lambda x: step_id + "/" + x["outputId"], output_expressions))
                                },
                                "input_names": {
                                    "default": list(map(lambda x: "__output_" + x["outputId"], output_expressions))
                                },
                                "expressions": {
                                    "default": list(map(lambda x: {
                                        "expr": x["expr"],
                                        "self": "__output_" + x["outputId"]
                                    }, output_expressions))
                                }
                            },
                            expression_lib_dict_pair
                        ),
                        "out": ["output"]
                    }


                get_cwl_map(new_workflow_cwl["steps"], step_id, "id")["run"] = {
                    "class": "Workflow",
                    "inputs": dict(map(lambda input_name: (input_name, {
                        "type": "Any"
                    }), step["in"].keys())),
                    "outputs": dict(map(get_output_from_name, step["out"])),
                    "steps": filter(None, [
                        workflow_expr_step,
                        workflow_expr_process_step,
                        runtime_expr_step,
                        inputs_expr_step,
                        {
                            "id": step_id
                            "in": update_dict(
                                dict(zip(step["in"].keys(), step["in"].keys())),
                                [(EXPR_SYMBOL, "__eval_exprs/output")]
                            ),
                            "out": step["out"],
                            "run": step["run"]
                        },
                        output_processing_step
                    ])
                }
            else:
                write_new_cwl(step_run_location, step_cwl)
        elif step_cwl["class"] == "Workflow":
            unjsify_workflow(step_run_location, outdir, base_cwldir)
        elif step_cwl["class"] == "ExpressionTool":
            write_new_cwl(step_run_location, step_cwl)

    write_new_cwl(workflow_location, new_workflow_cwl)

def inplace_nested_map(func, struct):
    if isinstance(struct, dict):
        for key, value in struct.items():
            struct[key] = inplace_nested_map(func, value)
        return struct
    elif isinstance(struct, list):
        for i, item in enumerate(struct):
            struct[i] = inplace_nested_map(func, item)
        return struct
    else:
        return func(struct)

def replace_expr(node, on_found_expr):
    value_arr = list(node)
    unscanned_str = node
    scan_slice = scan_expression(unscanned_str)

    while scan_slice:
        if unscanned_str[scan_slice[0]] == '$':
            expression = unscanned_str[scan_slice[0]:scan_slice[1]]
            if not is_parameter_reference(unscanned_str[scan_slice[0]+2:scan_slice[1]-1]):
                value_arr[scan_slice[0]+2:scan_slice[1]-1] = list(on_found_expr(expression))

        unscanned_str = unscanned_str[scan_slice[1]:]
        scan_slice = scan_expression(unscanned_str)

    return "".join(value_arr)

def unjsify_tool(cwl):
    input_expressions = []
    output_expressions = []
    for _input in cwl["inputs"]:
        if isinstance(_input, str):
            input = cwl["inputs"][_input]
            input_id = _input
        else:
            input = _input
            input_id = _input["id"]

        def on_found_input_expr(expression):
            input_expressions.append({"self": input_id, "expr": expression})
            return f"inputs.{EXPR_SYMBOL}[{len(input_expressions) - 1}]"

        if input.get("inputBinding", {}).get("valueFrom") is not None:
            input["inputBinding"]["valueFrom"] = replace_expr(input["inputBinding"]["valueFrom"], on_found_input_expr)

    data_by_outputId = {}

    for _output in cwl["outputs"]:
        if isinstance(_output, str):
            output = cwl["outputs"][_output]
            output_id = _output
        else:
            output = _output
            output_id = _output["id"]

        def on_found_output_expr(expression):
            output_expressions.append({"outputId": output_id, "expr": expression})
            return f"self[{len(output_expressions) - 1}]"

        if output.get("outputBinding", {}).get("outputEval") is not None:
            output["outputBinding"]["outputEval"] = replace_expr(output["outputBinding"]["outputEval"], on_found_output_expr)
            data_by_outputId[output_id] = {
                "outputEval": output["outputBinding"]["outputEval"],
                "type": output["type"]
            }
            del output["outputBinding"]["outputEval"]
            output["type"] = "Any"

    def on_found_expr(expression):
        input_expressions.append({"self": None, "expr": expression})
        return f"inputs.{EXPR_SYMBOL}[{len(input_expressions) - 1}]"

    def visit_cwl_node(node):
        if isinstance(node, str):
            return replace_expr(node, on_found_expr)
        else:
            return node

    add_cwl_map(cwl["inputs"], EXPR_SYMBOL, "id", {
        "type": {
            "type": "array",
            "items": "Any"
        }
    })

    remove_cwl_map(cwl["requirements"], "InlineJavascriptRequirement", "class")

    inplace_nested_map(visit_cwl_node, cwl)

    return input_expressions, output_expressions, data_by_outputId, cwl

def main():
    parser = argparse.ArgumentParser("unjsify")
    parser.add_argument("cwl_workflow", help="Initial CWL workflow file to unjsify.")
    parser.add_argument("-b", "--base-dir", help="Base directory for the CWL files")
    parser.add_argument("-o", "--output", help="Output directory for results.")
    parser.add_argument("--cwltool", help="Run cwltool with inputs specified.")
    args = parser.parse_args()

    if args.base_dir is None:
        args.base_dir = path.dirname(args.cwl_workflow)

    if args.cwltool is not None:
        with tempfile.TemporaryDirectory("unjsify") as tmpfolder:
            unjsify(args.cwl_workflow, tmpfolder, args.base_dir)
            os.system(f"cwltool {args.cwl_workflow} {args.cwltool}")

        return

    unjsify(args.cwl_workflow, args.output, args.base_dir)

if __name__ == "__main__":
    main()
