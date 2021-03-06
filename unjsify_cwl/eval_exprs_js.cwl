cwlVersion: v1.0
class: CommandLineTool
doc: Evaluate a series of JavaScript expressions

hints:
  DockerRequirement:
    dockerPull: node

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

          let input_values = JSON.parse(fs.readFileSync("input_values.json"))["input_values"];
          const input_names = JSON.parse(fs.readFileSync("input_names.json"))["input_names"];
          const expressions = JSON.parse(fs.readFileSync("expressions.json"))["expressions"];
          const expressionLib = fs.readFileSync("expressionLib.js");

          // if(!Array.isArray(input_values)){
          //  input_values = [input_values];
          // }

          if(input_values.length !== input_names.length){
            throw Error(input_values.length + "!==" + input_names.length)
          }

          let inputs = {};
          input_values.forEach((input_value, i) => {
            const input_name = input_names[i];

            if(Array.isArray(input_name)){
              console.error("hi", input_name, input_value)
              if(input_value === null){
                inputs[input_name[0]] = input_name[1];
              }
              else{
                inputs[input_name[0]] = input_value;
              }
            }
            inputs[input_name] = input_value;
          })

          const new_expressions = expressions.map((expression) => {
            if(expression.expr[1] == "{")
              expression.expr = "(() => {" + expression.expr.slice(2, -1) + "})()";
            else
              expression.expr = expression.expr.slice(2, -1);

            if(expression.self !== null && inputs[expression.self] === undefined){
              throw Error("Invalid self value " + expression.self);
            }

            return require("vm").runInNewContext(expressionLib + "var result = " + expression.expr + ";result", {
                inputs: inputs,
                self: expression.self == null?null:inputs[expression.self],
                runtime: undefined,
                console: Object.freeze({
                  log: (str) => {
                    console.log(str)
                  },
                  error: (str) => {
                    console.error(str)
                  }
                })
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
    type: Any?
  - id: input_names
    type: Any
  - id: expressions
    type: Any
  - id: expressionLib
    default: ""
    type: string?

outputs:
  - id: output
    type: Any