cwlVersion: v1.0
class: CommandLineTool
doc: Evaluate a series of Python expressions

requirements:
  InitialWorkDirRequirement:
    listing:
      - entryname: input_values.json
        entry: '{"input_values": $(inputs.input_values)}'
      - entryname: input_names.json
        entry: '{"input_names": $(inputs.input_names)}'
      - entryname: expressions.json
        entry: '{"expressions": $(inputs.expressions)}'
      - entryname: expressionLib.py
        entry: $(inputs.expressionLib)
      - entryname: driver.py
        entry: |
          import textwrap
          import json
          from typing import Any, List

          with open("input_values.json") as f:
              input_values = json.load(f)["input_values"]

          with open("input_names.json") as f:
              input_names = json.load(f)["input_names"]

          with open("expressions.json") as f:
              expressions = json.load(f)["expressions"]

          with open("expressionLib.py") as f:
              expression_lib = f.read()

          if not isinstance(input_values, list):
              input_values = [input_values]

          if len(input_values) != len(input_names):
              raise ValueError(f"{len(input_values)} != {len(input_names)}")

          inputs = dict(zip(input_names, input_values))

          new_expressions: List[Any] = []
          for expression in expressions:
              if expression["expr"][1] == "{":
                  expression["expr"] = (
                      "def x():\n" + textwrap.indent(expression["expr"][2:-1], " ") +
                          "\n__capture_output(x())"
                  )
              else:
                  expression["expr"] = "__capture_output(" + expression["expr"][2:-1] + ")"

              if expression["self"] not in inputs:
                  raise ValueError(f"Invalid self value {expression['self']}")

              result = None
              def __capture_output(value):
                  global result
                  result = value

              exec(expression_lib + "\n" + expression["expr"], {
                  "inputs": inputs,
                  "self": None if expression["self"] is None else inputs[expression["self"]],
                  "runtime": None,
                  "__capture_output": __capture_output
              })

              new_expressions.append(result)

          with open("cwl.output.json", "w") as f:
              json.dump({"output": new_expressions}, f)

baseCommand:
  - python
  - driver.py

inputs:
  - id: input_values
    type: Any
  - id: input_names
    type:
      type: array
      items: string
  - id: expressions
    type: Any
  - id: expressionLib
    default: ""
    type: string?

outputs:
  - id: output
    type: Any