import json
from readygate.probe import validate_response,validate_response_repaired
raw={'choices':[{'message':{'role':'assistant','tool_calls':[{'id':'call-1','type':'function','function':{'name':'get_weather','arguments':"{'location':'Tokyo'}"}}]}}]}
a=validate_response(raw,('get_weather',));b=validate_response_repaired(raw,('get_weather',))
print(json.dumps({'input_arguments':raw['choices'][0]['message']['tool_calls'][0]['function']['arguments'],'strict_layers':a.layers,'repaired_layers':b.layers,'strict_pass':a.passed,'repaired_pass':b.passed},indent=2))
