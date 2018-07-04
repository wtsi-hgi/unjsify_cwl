cwlVersion: v1.0
class: CommandLineTool
requirements:
  - class: InlineJavascriptRequirement
baseCommand: ['echo']

inputs:
  - id: number
    type: int
    inputBinding:
      valueFrom: ${return inputs.number * 2}

outputs: []
