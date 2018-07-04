cwlVersion: v1.0
class: Workflow
requirements:
  - class: InlineJavascriptRequirement
  - class: StepInputExpressionRequirement

inputs:
  - id: number
    type: int
    streamable: True
    default: p

steps:
  - id: test_tool_num1
    run: ./test_tool.cwl
    in:
      number:
        source: number
        valueFrom: $(true?self:self)
    out: []
  - id: test_tool_num2
    run: ./test_tool.cwl
    in:
      number:
        source: number
        valueFrom: $(true?self:self)
    out: []

outputs: []

