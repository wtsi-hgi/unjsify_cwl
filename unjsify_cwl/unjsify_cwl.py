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

import pkg_resources
import ruamel.yaml as yaml

from .get_expressions import scan_expression


def dict_map(func, d):
    return dict([func(key, value) for key, value in d.items()])

EXPR_SYMBOL = "__exprs"

def get_cwl_map(cwl_map, name, id_token):
    if isinstance(cwl_map, dict):
        return cwl_map.get(name)
    else:
        for requirement in cwl_map:
            if requirement[id_token] == name:
                return requirement

def remove_cwl_map(cwl_map, name, id_token):
    if isinstance(cwl_map, dict):
        del cwl_map[name]
    else:
        for requirement in cwl_map:
            if requirement[id_token] == name:
                cwl_map.remove(requirement)

def add_cwl_map(cwl_map, name, id_token, object=None):
    if object is None:
        object = {}

    if isinstance(cwl_map, dict):
        cwl_map[name] = object
    else:
        object[id_token] = name

        cwl_map.append(object)

    return object


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

def unjsify_workflow(workflow_location: str, outdir: str, base_cwldir: str):
    print(f"Processing {workflow_location}")
    def write_new_cwl(old_location, cwl):
        if not is_path_in(old_location, base_cwldir):
            raise Exception(f"Invalid reference to file {old_location}, outside the basedir of {base_cwldir}")

        out_file = path.join(outdir, path.relpath(old_location, base_cwldir))

        os.makedirs(path.dirname(out_file), exist_ok=True)

        with open(out_file, "w") as output_file:
            yaml.dump(cwl, output_file, default_flow_style=False)

    with open(workflow_location) as workflow_file:
        workflow_cwl = yaml.load(workflow_file, Loader=yaml.Loader)

    new_workflow_cwl = copy.deepcopy(workflow_cwl)

    if "requirements" not in new_workflow_cwl:
        new_workflow_cwl["requirements"] = []

    # this is needed to pass multiple inputs to the expression evaluation step
    add_cwl_map(new_workflow_cwl["requirements"], "MultipleInputFeatureRequirement", "class")

    for i, step in enumerate(workflow_cwl["steps"]):
        step_run_location = step["run"]
        if not path.isabs(step_run_location):
            step_run_location = path.join(path.dirname(workflow_location), step_run_location)
        with open(step_run_location) as fp:
            step_cwl = yaml.load(fp, Loader=yaml.Loader)

        if step_cwl["class"] == "CommandLineTool":
            js_req = get_cwl_map(step_cwl.get("requirements", []), "InlineJavascriptRequirement", "class")

            if js_req is not None:
                expressions, new_tool = unjsify_tool(step_cwl)
                write_new_cwl(step_run_location, new_tool)

                input_values_set = set()
                input_mappings = {} # type: Dict[str, Any]
                for in_key, in_value in step["in"].items():
                    if isinstance(in_value, dict) and in_value.keys() == ["source"]:
                        in_value = in_value["source"]

                    if isinstance(in_value, dict):
                        if in_value.keys() == ["default"]:
                            input_mappings[in_key] = in_value
                        else:
                            raise NotImplementedError(workflow_location)
                            in_value = "NOT IMPLEMENTED"
                    elif isinstance(in_value, str):
                        input_values_set.add(in_value)
                        input_mappings[in_key] = in_value
                    elif isinstance(in_value, list):
                        input_values_set = input_values_set.union(in_value)
                        input_mappings[in_key] = in_value
                    else:
                        raise Exception("Unknown in_value")

                input_values_list = list(input_values_set)
                inverse_input_values_list = dict(zip(input_values_list, itertools.count()))

                for input_mapping_key, input_mapping_value in input_mappings.items():
                    if isinstance(input_mapping_value, str):
                        input_mappings[input_mapping_key] = inverse_input_values_list[input_mapping_value]
                    else:
                        for i, v in enumerate(input_mapping_value):
                            input_mapping_value[i] = inverse_input_values_list[v]

                new_workflow_cwl["steps"][i]["run"] = {
                    "class": "Workflow",
                    "inputs": dict(map(lambda input_name: (input_name, {
                        "type": "Any"
                    }), step["in"].keys())),
                    "outputs": dict(map(lambda output_name: (output_name, {
                        "type": "Any",
                        "outputSource": f'{step["id"]}/{output_name}'
                    }), step["out"])),
                    "steps": {
                        "__eval_exprs": {
                            "run": path.relpath(path.join(base_cwldir, "eval_exprs.cwl"), path.dirname(workflow_location)),
                            "in": update_dict(
                                {
                                    "input_values": {
                                        "source": step["in"].keys()
                                    },
                                    "input_names": {
                                        "default": step["in"].keys()
                                    },
                                    "expressions": {
                                        "default": expressions
                                    }
                                },
                                [("expressionLib", ";".join(js_req["expressionLib"])] \
                                    if js_req.get("expressionLib") is not None else []
                            ),
                            "out": ["output"]
                        },
                        step["id"]: {
                            "in": update_dict(
                                dict(zip(step["in"].keys(), step["in"].keys())),
                                [(EXPR_SYMBOL, "__eval_exprs/output")]
                            )
                        }
                    }
                }

                new_workflow_cwl["steps"].insert(i, {
                    "id": "pre_" + step["id"],
                    "run": path.relpath(path.join(base_cwldir, "eval_exprs.cwl"), path.dirname(workflow_location)),
                    "in": {
                        "input_values": {
                            "source": input_values_list
                        },
                        "input_mappings": {
                            "default": json.dumps(input_mappings)
                        },
                        "expressions": {
                            "default": expressions
                        }
                    },
                    "out": ["output"]
                })

                if js_req.get("expressionLib") is not None:
                    new_workflow_cwl["steps"][i]["in"]["expressionLib"] = ";".join(js_req["expressionLib"])

                new_workflow_cwl["steps"][i + 1]["in"][EXPR_SYMBOL] = f"pre_{step['id']}/output"
            else:
                write_new_cwl(step_run_location, step_cwl)
        elif step_cwl["class"] == "Workflow":
            unjsify_workflow(step_run_location, outdir, base_cwldir)
        elif step_cwl["class"] == "ExpressionTool":
            write_new_cwl(step_run_location, step_cwl)
            print(f"Not transforming ExpressionTool file {step_run_location}")

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

def unjsify_tool(cwl):
    expressions = []
    def visit_cwl_node(node):
        if isinstance(node, str):
            value_arr = list(node)
            unscanned_str = node
            scan_slice = scan_expression(unscanned_str)

            while scan_slice:
                if unscanned_str[scan_slice[0]] == '$':
                    expression = unscanned_str[scan_slice[0]:scan_slice[1]]
                    expressions.append(expression)
                    value_arr[scan_slice[0]+2:scan_slice[1]-1] = \
                        list(f"inputs.{EXPR_SYMBOL}[{len(expressions) - 1}]")

                unscanned_str = unscanned_str[scan_slice[1]:]
                scan_slice = scan_expression(unscanned_str)

            return "".join(value_arr)
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

    return expressions, cwl

def main():
    parser = argparse.ArgumentParser("unjsify")
    parser.add_argument("cwl_workflow", help="Initial CWL workflow file to unjsify.")
    parser.add_argument("-b", "--base-dir", help="Base directory for the CWL files")
    parser.add_argument("-o", "--output", required=True, help="Output directory for results.")
    args = parser.parse_args()

    if args.base_dir is None:
        args.base_dir = path.dirname(args.output)

    unjsify(args.cwl_workflow, args.output, args.base_dir)

if __name__ == "__main__":
    main()
