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
from collections import namedtuple
import time

import pkg_resources
import ruamel.yaml as yaml

from .get_expressions import scan_expression, is_parameter_reference
from . import cwl_model

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
        return list(map(lambda key: {
            **to_dict(cwl_map[key]),
            id_token: key
        }, cwl_map.keys()))
    else:
        return cwl_map

def is_path_in(test_path, containing_path):
    return path.commonpath([path.abspath(test_path), path.abspath(containing_path)]) == path.abspath(containing_path)

def unjsify(workflow_location: str, outdir: str, base_cwldir: str, language: str):
    if not path.isdir(outdir):
        os.mkdir(outdir)

    if language == "js":
        eval_exprs_filename = "eval_exprs_js.cwl"
    elif language == "python":
        eval_exprs_filename = "eval_exprs_python.cwl"
    else:
        raise ValueError

    with open(path.join(outdir, "eval_exprs.cwl"), "wb") as eval_exprs_dest:
        with pkg_resources.resource_stream(__name__, eval_exprs_filename) as eval_exprs_source:
            shutil.copyfileobj(eval_exprs_source, eval_exprs_dest)

    return unjsify_workflow(workflow_location, outdir, base_cwldir)


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

from ruamel.yaml.comments import CommentedMap, CommentedSeq

def pureify(cwl):
    def pureify_node(node):
        if isinstance(node, CommentedMap):
            return dict(node)
        elif isinstance(node, CommentedSeq):
            return list(node)
        else:
            return node

    return inplace_nested_map(pureify_node, cwl)

def expand_cwl(cwl, cwl_dir):
    if isinstance(cwl, dict):
        if "$include" in cwl:
            with open(path.join(cwl_dir, cwl["$include"])) as fp:
                return fp.read()
        elif "$import" in cwl:
            with open(path.join(cwl_dir, cwl["$import"])) as fp:
                return yaml.load(fp, Loader=yaml.Loader)
        else:
            for key, value in cwl.items():
                cwl[key] = expand_cwl(value, cwl_dir)

        return cwl
    elif isinstance(cwl, list):
        for i, item in enumerate(cwl):
            cwl[i] = expand_cwl(item, cwl_dir)

        return cwl
    else:
        return cwl

def relativise(cwl, base_cwl_filename):
    this_cwl_filename = "file://" + base_cwl_filename

    def relativise_str(s, base_id):
        if s.startswith(base_id):
            return s[len(base_id) + 1:].replace("#", "")
        elif s.startswith(this_cwl_filename):
            return "#" + s[len(this_cwl_filename) + 1:].replace("#", "")
        elif s.startswith("file://"):
            return path.relpath(base_id, s)
        else:
            return s

    def relativise_node(node, base_id):
        if isinstance(node, dict) and node.get("id") is not None:
            old_node_id = node["id"]
            node["id"] = relativise_str(node["id"], base_id)
            base_id = old_node_id
        if isinstance(node, str):
            return relativise_str(node, base_id), base_id
        else:
            return node, base_id

    return inplace_nested_map_with_state(relativise_node, cwl, this_cwl_filename)

def load_cwl_document(cwl_path):
    # url = "file://" + path.abspath(cwl_path)
    # raw_cwl = metaschema_loader.fetch(url)
    # schema_doc, _ = metaschema_loader.resolve_all(raw_cwl, url)
    print(cwl_path, file=sys.stderr)
    return relativise(
        cwl_model.save(cwl_model.load_document("file://" + path.abspath(cwl_path), "")),
        path.abspath(cwl_path)
    )

def get_cwl(cwl_path):
    global cwl_file_cache

    hash_pos = cwl_path.find("#")

    if hash_pos != -1:
        hash_part = cwl_path[hash_pos+1:]
        cwl_path = cwl_path[:hash_pos]

    if cwl_file_cache.get(cwl_path) is not None:
        cwl = cwl_file_cache[cwl_path]
    else:
        cwl = load_cwl_document(cwl_path)

        cwl_file_cache[cwl_path] = copy.deepcopy(cwl)

    if hash_pos != -1:
        assert isinstance(cwl, list)

        for cwl_file in cwl:
            if cwl_file["id"] == hash_part:
                return pureify(cwl)

        raise ValueError(f"Not found hash {hash_pos} in cwl graph")
    else:
        return pureify(cwl)

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

def flatten(lst):
    return [item for sublist in lst for item in sublist]

def get_identity_workflow(steps_names):
    return {
        "class": "Workflow",
        "inputs": dict(zip(map(lambda x: x + "_in", steps_names), iterate(lambda: {"type": "Any?"}))),
        "outputs":  dict(map(lambda x: (x, {
            "type": "Any?",
            "outputSource": x + "_in"
        }), steps_names)),
        "steps": []
    }

def steralize_name(name: str):
    try:
        return name.replace("#", "")
    except Exception:
        import pdb; pdb.set_trace()

JSONType = Dict[str, Any]

EVAL_WORKFLOW_EXPRS = "__eval_workflow_exprs"
PROCESS_WORKFLOW_EXPRS = "__process_workflow_exprs"
EVAL_INPUT_EXPRS = "__eval_input_exprs"
EVAL_OUTPUT_EXPRS = "__eval_output_exprs"

WorkflowExprReplacement = namedtuple(
    "WorkflowExprReplacement",
    ["id", "new_valueFrom", "processing_expressions"]
)

def get_workflow_expr_replacements(step):
    workflow_ids = []
    new_value_froms = []
    processing_expressions = []
    for step_in in step["in"]:
        if isinstance(step_in, dict):
            if step_in.get("valueFrom") is not None:
                found_expr = False
                def on_found_workflow_expr(expression):
                    nonlocal found_expr

                    found_expr = True
                    processing_expressions.append({"self": f'{step_in["id"]}', "expr": expression})
                    parameter_reference = f"inputs.{OUTPUT_EXPR_SYMBOL}[{len(processing_expressions) - 1}]"

                    return parameter_reference

                new_valueFrom = replace_expr(step_in["valueFrom"], on_found_workflow_expr)

                if found_expr:
                    workflow_ids.append(step_in["id"])
                    new_value_froms.append(new_valueFrom)

    return workflow_ids, new_value_froms, processing_expressions


def unjsify_workflow_exprs(workflow_step, eval_exprs_location, expressionLib):
    ids, new_value_froms, processing_expressions = get_workflow_expr_replacements(workflow_step)
    new_workflow_step = copy.deepcopy(workflow_step)

    if expressionLib is None:
        workflow_expression_lib_dict = {}
    else:
        workflow_expression_lib_dict = {
            "expressionLib": {
                "default": ";".join(expressionLib)
            }
        }

    for id_to_delete in ids:
        del new_workflow_step["in"][id_to_delete]["valueFrom"]

    workflow_expr_step = {
        "id": EVAL_WORKFLOW_EXPRS,
        "run": eval_exprs_location,
        "in": {
            "input_values": {
                "source": list(workflow_step["in"].keys())
            },
            "input_names": {
                "default": list(workflow_step["in"].keys())
            },
            "expressions": {
                "default": processing_expressions
            },
            **workflow_expression_lib_dict
        },
        "out": ["output"]
    }

    workflow_expr_process_step = {
        "id": PROCESS_WORKFLOW_EXPRS,
        "in": {
            "__output_exprs": "__eval_workflow_exprs/output",
            **dict(list(map(
                lambda x: (
                    x[0] + "_in",
                    {"valueFrom": x[1]}
                ),
                zip(ids, new_value_froms)
            )))
        },
        "run": get_identity_workflow(ids),
        "out": list(ids)
    }

    redirections = dict(zip(
        ids,
        map(lambda x: f"{PROCESS_WORKFLOW_EXPRS}/{x}", ids)
    ))

    return new_workflow_step, (workflow_expr_step, workflow_expr_process_step), redirections

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
        inputs_ids = list(map(steralize_name, get_map_keys(workflow_cwl["inputs"], "id")))

        workflow_cwl = {
            "cwlVersion": "v1.0",
            "class": "Workflow",
            "inputs": dict(zip(inputs_ids, iterate(lambda: {"type": "Any?"}))),
            "outputs": dict(map(lambda x: (x, {"outputSource": "cmdline_tool/" + x, "type": "Any?"}),
                get_map_keys(workflow_cwl["outputs"], "id"))),
            "requirements": [{
                "class": "SubworkflowFeatureRequirement"
            }],
            "steps": [{
                "id": "cmdline_tool",
                "run": "__" + path.basename(workflow_location),
                "in": dict(zip(inputs_ids, inputs_ids)),
                "out": list(get_map_keys(workflow_cwl["outputs"], "id"))
            }]
        }

        global cwl_file_cache
        cwl_file_cache[resolve_path(workflow_location, "__" + path.basename(workflow_location))] = get_cwl(workflow_location)

    new_workflow_cwl = copy.deepcopy(workflow_cwl)

    workflow_expression_lib = None
    if get_cwl_map(workflow_cwl.get("requirements", {}), "InlineJavascriptRequirement", "class") is not None:
        workflow_expression_lib = get_cwl_map(workflow_cwl["requirements"], "InlineJavascriptRequirement", "class").get("expressionLib", None)
        remove_cwl_map(new_workflow_cwl["requirements"], "InlineJavascriptRequirement", "class")


    if "requirements" not in new_workflow_cwl:
        new_workflow_cwl["requirements"] = []

    # this is needed to pass multiple inputs to the expression evaluation step and have subworkflows for grouping
    add_cwl_map(new_workflow_cwl["requirements"], "MultipleInputFeatureRequirement", "class")
    add_cwl_map(new_workflow_cwl["requirements"], "SubworkflowFeatureRequirement", "class")
    add_cwl_map(new_workflow_cwl["requirements"], "StepInputExpressionRequirement", "class")

    eval_exprs_location = path.relpath(path.join(base_cwldir, "eval_exprs.cwl"), path.dirname(workflow_location))

    for i, step in enumerate(workflow_cwl["steps"]):
        step_id = step["id"]
        if isinstance(step["run"], str):
            step_run_location = resolve_path(workflow_location, step["run"])
            step_cwl = get_cwl(step_run_location)
        else:
            raise NotImplementedError()

        #### Init steps
        workflow_expr_step = None # type: JSONType
        workflow_expr_process_step = None # type: JSONType
        runtime_expr_step = None # type: JSONType
        inputs_expr_step = None # type: JSONType
        output_processing_step = None # type: JSONType

        result = unjsify_workflow_exprs(step, eval_exprs_location, workflow_expression_lib)
        new_workflow_cwl["steps"][i] = result[0]
        workflow_expr_step, workflow_expr_process_step = result[1]
        workflow_step_replacements = result[2]

        if step_cwl["class"] in ("CommandLineTool", "ExpressionTool"):
            js_req = get_cwl_map(step_cwl.get("requirements", []), "InlineJavascriptRequirement", "class")
            data_by_outputId = {}

            if step_cwl["class"] == "ExpressionTool":
                step_cwl["class"] = "CommandLineTool"
                step_cwl["arguments"] = ["bash", "-c", 'echo $0 | cut -c 2- > cwl.output.json', "|" + step_cwl["expression"]]
                del step_cwl["expression"]

                js_req = {}

            if js_req is not None:
                input_expressions, output_expressions, data_by_outputId, new_tool = unjsify_tool(step_cwl)
                write_new_cwl(step_run_location, new_tool)

                if js_req.get("expressionLib") is None:
                    expression_lib_dict = {} # type: JSONType
                else:
                    expression_lib_dict = {
                        "expressionLib": {"default": ";".join(js_req["expressionLib"])}
                    }

                def add_defaults(step_input_name):
                    if "default" in get_cwl_map(step_cwl["inputs"], step_input_name):
                        default_value = get_cwl_map(step_cwl["inputs"], step_input_name)["default"]

                        return [step_input_name, default_value]
                    else:
                        return step_input_name

                if len(input_expressions) != 0:
                    inputs_expr_step = {
                        "id": EVAL_INPUT_EXPRS,
                        "run": eval_exprs_location,
                        "in": {
                            "input_values": {
                                "source": list(step["in"].keys())
                            },
                            "input_names": {
                                "default": list(map(add_defaults, step["in"].keys()))
                            },
                            "expressions": {
                                "default": input_expressions
                            },
                            **expression_lib_dict
                        },
                        "out": ["output"]
                    }

                if output_expressions != []:
                    output_processing_step = {
                        "id": EVAL_OUTPUT_EXPRS,
                        "run": eval_exprs_location,
                        "in": {
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
                            },
                            **expression_lib_dict
                        },
                        "out": ["output"]
                    }
            else:
                write_new_cwl(step_run_location, step_cwl)

            def get_output_from_name(output_name):
                if data_by_outputId.get(output_name) is not None:
                    return (output_name, {
                        "outputSource": f'{EVAL_OUTPUT_EXPRS}/output',
                        "outputBinding": {
                            "outputEval": data_by_outputId[output_name]["outputEval"]
                        },
                        "type": data_by_outputId[output_name]["type"]
                    })
                return (output_name, {
                    "type": "Any?",
                    "outputSource": f'{step_id}/{output_name}'
                })

            if any([workflow_expr_step, workflow_expr_process_step, runtime_expr_step, inputs_expr_step, output_processing_step]):
                get_cwl_map(new_workflow_cwl["steps"], step_id, "id")["run"] = {
                    "class": "Workflow",
                    "inputs": dict(map(lambda input_name: (input_name, {
                        "type": "Any?"
                    }), step["in"].keys())),
                    "outputs": dict(map(get_output_from_name, step["out"])),
                    "steps": list(filter(None, [
                        workflow_expr_step,
                        workflow_expr_process_step,
                        runtime_expr_step,
                        inputs_expr_step,
                        {
                            "id": step_id,
                            "in": {
                                **dict(zip(step["in"].keys(), step["in"].keys())),
                                **dict(map(reversed, workflow_step_replacements.items())),
                                **({EXPR_SYMBOL: f"{EVAL_INPUT_EXPRS}/output"} if inputs_expr_step is not None else {})
                            },
                            "out": step["out"],
                            "run": step["run"]
                        },
                        output_processing_step
                    ]))
                }

        elif step_cwl["class"] == "Workflow":
            unjsify_workflow(step_run_location, outdir, base_cwldir, language)
        else:
            raise Exception(f'Unknown step type {step_cwl["class"]}')

    write_new_cwl(workflow_location, new_workflow_cwl)

def inplace_nested_leaf_map(func, struct):
    if isinstance(struct, dict):
        for key, value in struct.items():
            struct[key] = inplace_nested_leaf_map(func, value)
        return struct
    elif isinstance(struct, list):
        for i, item in enumerate(struct):
            struct[i] = inplace_nested_leaf_map(func, item)
        return struct
    else:
        return func(struct)


def inplace_nested_map_with_state(func, struct, state=None):
    if state is None:
        state = {}

    if isinstance(struct, dict):
        for key, value in struct.items():
            struct[key] = inplace_nested_map_with_state(func, *func(value, copy.deepcopy(state)))
        return struct
    elif isinstance(struct, list):
        for i, item in enumerate(struct):
            struct[i] = inplace_nested_map_with_state(func, *func(item, copy.deepcopy(state)))
        return struct
    else:
        return func(struct, copy.deepcopy(state))[0]

def inplace_nested_map(func, struct):
    if isinstance(struct, dict):
        for key, value in struct.items():
            struct[key] = inplace_nested_map(func, func(value))
        return struct
    elif isinstance(struct, list):
        for i, item in enumerate(struct):
            struct[i] = inplace_nested_map(func, func(item))
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
                value_arr[scan_slice[0]:scan_slice[1]] = list("$(" + on_found_expr(expression) + ")")

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

        if output.get("outputBinding", {}).get("outputEval") is not None:
            found_output_expression = False

            def on_found_output_expr(expression):
                nonlocal found_output_expression
                found_output_expression = True
                output_expressions.append({"outputId": output_id, "expr": expression})
                return f"self[{len(output_expressions) - 1}]"

            output["outputBinding"]["outputEval"] = replace_expr(output["outputBinding"]["outputEval"], on_found_output_expr)

            if found_output_expression:
                data_by_outputId[output_id] = {
                    "outputEval": output["outputBinding"]["outputEval"],
                    "type": output["type"]
                }
                del output["outputBinding"]["outputEval"]
                output["type"] = "Any?"

    def on_found_expr(expression):
        input_expressions.append({"self": None, "expr": expression})
        return f"inputs.{EXPR_SYMBOL}[{len(input_expressions) - 1}]"

    def visit_cwl_node(node):
        if isinstance(node, str):
            return replace_expr(node, on_found_expr)
        else:
            return node

    inplace_nested_leaf_map(visit_cwl_node, cwl)
    remove_cwl_map(cwl["requirements"], "InlineJavascriptRequirement", "class")

    if len(input_expressions) != 0:
        add_cwl_map(cwl["inputs"], EXPR_SYMBOL, "id", {
            "type": {
                "type": "array",
                "items": ["Any", "null"]
            }
        })


    return input_expressions, output_expressions, data_by_outputId, cwl

def main():
    parser = argparse.ArgumentParser(__name__)
    parser.add_argument("cwl_workflow", help="Initial CWL workflow or tool to unjsify.")
    parser.add_argument("-b", "--base-dir", help="Base directory for the CWL files")
    parser.add_argument("-o", "--output", help="Output directory for results.")
    parser.add_argument("--language", help="Language to use ('js' or 'python').", default="js")
    args = parser.parse_args()

    if args.base_dir is None:
        args.base_dir = path.dirname(args.cwl_workflow)
    unjsify(args.cwl_workflow, args.output, args.base_dir, args.language)

if __name__ == "__main__":
    main()
