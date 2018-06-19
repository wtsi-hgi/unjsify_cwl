cwlVersion: v1.0
class: CommandLineTool
doc: Transpose a given matrix

requirements:
  InitialWorkDirRequirement:
    listing:
      - entryname: input_values.json
        entry: '{"input_values": $(inputs.input_values)}'
      - entryname: input_mappings.json
        entry: '{"input_mappings": $(inputs.input_mappings)}'
      - entryname: expressions.json
        entry: '{"expressions": $(inputs.expressions)}'
      - entryname: expressionLib.js
        entry: $(inputs.expressionLib)
      - entryname: driver.js
        entry: |
          const fs = require("fs");
          const vm = require("vm");

          const input_values = JSON.parse(fs.readFileSync("input_values.json"))["input_values"];
          const input_mappings = JSON.parse(JSON.parse(fs.readFileSync("input_mappings.json"))["input_mappings"]);
          const expressions = JSON.parse(fs.readFileSync("expressions.json"))["expressions"];
          const expressionLib = fs.readFileSync("expressionLib.js");

          let inputs = {};
          Object.entries(input_mappings).forEach(([input_key, input_value_i], i) => {
            if(typeof input_value_i == "number"){
              inputs[input_key] = input_values[input_value_i];
            }
            else{
              inputs[input_key] = input_value_i.map(x => input_values[x]);
            }
          })
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
                runtime: undefined,
                self: undefined,
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
  - id: input_mappings
    type: string
  - id: expressions
    type: Any
  - id: expressionLib
    default: ""
    type: string?
outputs:
  - id: output
    type: Any