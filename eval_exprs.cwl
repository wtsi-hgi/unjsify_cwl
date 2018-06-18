cwlVersion: v1.0
class: CommandLineTool
doc: Transpose a given matrix

requirements:
  InitialWorkDirRequirement:
    listing:
      - entryname: input_values.json
        entry: '{"input_values": $(inputs.input_values)}'
      - entryname: input_names.json
        entry: '{"input_names": $(inputs.input_names)}'
      - entryname: expressions.json
        entry: '{"expressions": $(inputs.expressions)}'
      - entryname: expressionLib.js
        entry: $(inputs.expressionLib)
      - entryname: driver.js
        entry: |
          const fs = require("fs");
          const vm = require("vm");

          const input_values = JSON.parse(fs.readFileSync("input_values.json"))["input_values"];
          const input_names = JSON.parse(fs.readFileSync("input_names.json"))["input_names"];
          const expressions = JSON.parse(fs.readFileSync("expressions.json"))["expressions"];
          const expressionLib = fs.readFileSync("expressionLib.js");

          if(input_values.length !== input_names.length){
            throw Error(input_values.length + "!==" + input_names.length)
          }

          let inputs = {};
          inputs_values.forEach((input_value, i) => {
            inputs[input_names[i]] = input_value;
          })

          const context_console_ob = Object.freeze({
            log: (str) => {
              console.log(str)
            },
            error: (str) => {
              console.error(str)
            }
          })

          const new_expressions = expressions.map((expression) => {
            if(expression[1] == "{")
              expression = "(() => {" + expression.slice(2, -1) + "})()";
            else
              expression = expression.slice(2, -1);

            return require("vm").runInNewContext(expressionLib + ";" + expression, {
                inputs:inputs
            });
          })

          fs.writeFileSync("cwl.output.json", JSON.stringify({
            output:new_expressions
          }))

baseCommand:
  - node
  - driver.js

inputs:
  - id: input_values
    type:
      type: array
      items:  Any
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