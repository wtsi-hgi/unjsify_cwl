import ruamel.yaml as yaml
import re
import sys
import copy
import os
import os.path as path
import argparse

def dict_map(func, d):
    return dict([func(key, value) for key, value in d.items()])

EXPR_SYMBOL = "__exprs"

def unjsify_workflow(workflow_location: str, output_dir: str, capdir: str):
    def write_new_cwl(old_location, cwl):
        out_file = path.join(output_dir, path.basename(old_location))
        if path.commonpath([out_file, capdir]) != capdir:
            raise Exception(f"Cannot write to {out_file}, it is out of the capdir of {capdir}")

        with open(out_file, "w") as output_file:
            yaml.dump(cwl, output_file)

    with open(workflow_location) as workflow_file:
        workflow_cwl = yaml.load(workflow_file, Loader=yaml.Loader)

    new_workflow_cwl = copy.deepcopy(workflow_cwl)

    for i, step in enumerate(workflow_cwl["steps"]):
        step_run_location = step["run"]
        if not path.isabs(step_run_location):
            step_run_location = path.join(path.dirname(workflow_location), step_run_location)
        with open(step_run_location) as fp:
            step_cwl = yaml.load(fp, Loader=yaml.Loader)

        if step_cwl["class"] == "CommandLineTool":
            for requirement in step_cwl["requirements"]:
                if requirement["class"] == "InlineJavascriptRequirement":
                    has_inline_js = True
                    expressionLib = requirement.get("expressionLib", None)

            if has_inline_js:
                expressions, new_tool = unjsify_tool(step_cwl)
                write_new_cwl(step_run_location, new_tool)
                if "requirements" not in new_workflow_cwl:
                    new_workflow_cwl["requirements"] = []

                new_workflow_cwl["requirements"].append({
                    "class": "MultipleInputFeatureRequirement"
                })

                new_workflow_cwl["steps"].insert(i, {
                    "id": "pre_" + step["id"],
                    "run": "./eval_exprs.cwl",
                    "in": {
                        "input_values": {
                            "source": list(step["in"].values())
                        },
                        "input_names": {
                            "default": list(step["in"].keys())
                        },
                        "expressions": {
                            "default": expressions
                        }
                    },
                    "out": ["output"]
                })

                if expressionLib is not None:
                    new_workflow_cwl["steps"][i]["in"]["expressionLib"] = ";".join(expressionLib)

                new_workflow_cwl["steps"][i + 1]["in"][EXPR_SYMBOL] = f"pre_{step['id']}/output"
        elif step_cwl["class"] == "Workflow":
            new_outdir = path.dirname(path.relpath(step_run_location, output_dir))
            if path.commonpath([new_outdir, capdir]) != capdir:
                raise Exception(f"Cannot write to {new_outdir}, it is out of the capdir of {capdir}")

            os.makedirs(new_outdir, exist_ok=True)

            unjsify_workflow(step_run_location, new_outdir, capdir)
        elif step_cwl["class"] == "ExpressionTool":
            raise NotImplementedError()

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
            for re_expr in re.finditer(r"\$\((.*?)\)", node):

                expressions.append(re_expr.groups()[0])
                value_arr[re_expr.span()[0]+2:re_expr.span()[0]-1] = \
                    list(f"inputs.{EXPR_SYMBOL}[{len(expressions) - 1}]")

            return "".join(value_arr)
        else:
            return node

    cwl["inputs"].insert(0, {
        "id": EXPR_SYMBOL,
        "type": {
            "type": "array",
            "items": "Any"
        }
    })


    for requirement in cwl["requirements"]:
        if requirement["class"] == "InlineJavascriptRequirement":
            cwl["requirements"].remove(requirement)

    inplace_nested_map(visit_cwl_node, cwl)

    return expressions, cwl

def main():
    parser = argparse.ArgumentParser("unjsify")
    parser.add_argument("cwl_workflow", required=True, help="Initial CWL workflow file to unjsify.")
    parser.add_argument("-o", "--output", required=True, help="Output directory for results.")
    args = parser.parse_args()

    if path.isdir(args.output):
        os.mkdir(args.output)

    unjsify_workflow(args.cwl_workflow, args.output, args.output)

if __name__ == "__main__":
    main()
