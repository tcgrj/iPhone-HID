"""Create an importable Siri shortcut; never copy the old AI provider's credentials."""
import json
from pathlib import Path
import plistlib
import argparse
import ipaddress
import uuid

root = Path(__file__).resolve().parents[1]
parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('host', help='Mac LAN IPv4, not the ESP32 address')
parser.add_argument('--takeaway', action='store_true')
args = parser.parse_args()
try:
    address = ipaddress.IPv4Address(args.host)
    if not address.is_private or address.is_loopback or address.is_unspecified or address.is_multicast:
        parser.error('Use the Mac private LAN IPv4 address')
except ipaddress.AddressValueError:
    parser.error('Invalid IPv4 address')
config_path = root / '.runtime/siri.json'
if not config_path.is_file():
    parser.error('Start the console with --siri-host first to create a private token')
config = json.loads(config_path.read_text())
if not isinstance(config.get('token'), str) or len(config['token']) < 16:
    parser.error('Invalid Siri token; stop the gateway and regenerate its private configuration')
takeaway = args.takeaway
name = '帮我点外卖' if takeaway else '科技阁助手'
output = root / '.runtime' / (name + '.unsigned.shortcut')
def text(s):
    return {'WFSerializationType':'WFTextTokenString', 'Value':{'string':s}}
def field(key, value):
    return {'WFKey':text(key), 'WFItemType':0, 'WFValue':value}
def dictionary(items):
    return {'WFSerializationType':'WFDictionaryFieldValue','Value':{'WFDictionaryFieldValueItems':items}}
def ref(ident, name):
    return {'Type':'ActionOutput','OutputUUID':ident,'OutputName':name}
ask, request, result = [str(uuid.uuid4()).upper() for _ in range(3)]
prefix = '打开美团外卖，查找并选择：' if takeaway else ''
suffix = '。加入购物车并进入结算，停在支付前，不提交订单、不付款。若缺少规格等必要信息，暂停并说明。' if takeaway else ''
input_text = text(prefix + '\ufffc' + suffix)
input_text['Value']['attachmentsByRange'] = {f'{{{len(prefix)}, 1}}':ref(ask,'提供的输入')}
actions = [
 {'WFWorkflowActionIdentifier':'is.workflow.actions.ask','WFWorkflowActionParameters':{'WFAskActionPrompt':('想吃什么？' if takeaway else '你说'),'WFInputType':'Text','UUID':ask}},
 {'WFWorkflowActionIdentifier':'is.workflow.actions.downloadurl','WFWorkflowActionParameters':{
  'WFURL':f'http://{address}:8769/task','WFHTTPMethod':'POST','WFHTTPBodyType':'JSON',
  'WFJSONValues':dictionary([field('task',input_text)]),
  'WFHTTPHeaders':dictionary([field('Authorization',text('Bearer '+config['token']))]),'ShowHeaders':True,'UUID':request}},
 {'WFWorkflowActionIdentifier':'is.workflow.actions.getvalueforkey','WFWorkflowActionParameters':{
  'UUID':result,'WFDictionaryKey':'message','WFInput':{'WFSerializationType':'WFTextTokenAttachment','Value':ref(request,'URL 的内容')}}},
 {'WFWorkflowActionIdentifier':'is.workflow.actions.dismisssiri','WFWorkflowActionParameters':{}},
 {'WFWorkflowActionIdentifier':'is.workflow.actions.returntohomescreen','WFWorkflowActionParameters':{}}
]
doc={'WFWorkflowActions':actions,'WFWorkflowClientVersion':'4000','WFWorkflowMinimumClientVersion':900,
 'WFWorkflowIcon':{'WFWorkflowIconStartColor':4282601983,'WFWorkflowIconGlyphNumber':59511},
 'WFWorkflowTypes':[],'WFWorkflowInputContentItemClasses':[],'WFWorkflowName':name,
 'WFWorkflowImportQuestions':[]}
output.write_bytes(plistlib.dumps(doc)); output.chmod(0o600)
print('Generated shortcut with five actions (credential omitted).')
