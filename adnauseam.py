#!/usr/bin/env python

"""

Monitors etcd and updates specified config files based
on provided templates.


Usage:
  adnauseam [(-t <template>)...] CMD...
 
Options:
  -h --help     Show this screen.
  --version     Show version.

Example:

adnauseam -t my.template:config.conf /usr/bin/command 
"""
__version__="0.0.1"

import os
import subprocess
from functools import partial


from codd import Tokens
from collections import namedtuple, defaultdict
import requests
from docopt import docopt

BASE_URL = "http://172.17.42.1:4001/v2/keys/foo"

Key = namedtuple('Key','path')


def main():  # pragma: no cover
  arguments = docopt(__doc__, version="AdNauseum " + __version__)

  monitor(
    arguments['CMD'],
    *arguments['<template>']
  )


def monitor(command, *args):  # pragma: no cover

  template_mapping = dict(a.split(':') for a in args)
  render, collect = compile_templates(template_mapping)
  collect_env(collect)

  # setup our statemachine with it's initial state
  statemachine = proc_statemachine(not_running, command)
  statemachine.send(None)


  try:
    index = 1
    while True:
      index = wait(collect, BASE_URL, index)
 
      if len(render()) == len(template_mapping):
        statemachine.send('start')
      else:
        statemachine.send('stop')

  except KeyboardInterrupt:
    print "...Finishing"



def tokenize(template):
  t = Tokens(template)
  while not t.at_end():
    if t.current_char == '{':
      path = t.read_until('}') + t.read_char()
      yield Key(path[1:-1].strip())
    else:
      yield t.read_until('{')


def keys(tokens):
  """
  Given a list of tokens return the key path
  Example

  >>> keys(['some text', Key('/path/1/'), 'foo'])
  ['/path/1/']
  """

  return [
    token.path
    for token in tokens
    if isinstance(token, Key)
  ]

def template(tokens, values):
  """
  Given a list of tokens[str | Key], and values. Replace the Key with
  the value found at values[key.path]

  >>> template(['Hi ', Key('name'),'!'], dict(name='Bob'))
  'Hi Bob!'
  """

  return "".join([
    t if not isinstance(t, Key) else values[t.path]
    for t in tokens
  ])



def compile(tokens):
  """
  Given a list of tokens returns a function template(ctx) -> rendered template
  
  Which when called returns a string with the tokens replaced.
  >>> compile(['Hi ', Key('name'),'!\\nHow are you?'])(dict(name='Bob'))
  'Hi Bob!\\nHow are you?'

  >>> compile(['This is ', Key('missing')])({})
  Traceback (most recent call last):
  ...
  KeyError: 'missing'
  """

  return partial(template, tokens)


def set_key(n, key, value):
  """
  Given a dictionary, key and value update the key and
  value and return the dictionary.
  TODO: make this return a copy of the dictionary

  >>> d = {}
  >>> set_key(d, 'blah', 'hi mom')
  {'blah': 'hi mom'}

  """
  n[key] = value
  return n

def del_key(n, key):
  """
  Given a dictionary and key remove the key  and
  return the dictionary.
  TODO: make this return a copy of the dictionary

  >>> d = {'blah': 'some value'}
  >>> del_key(d, 'blah')
  {}

  """
  del n[key]
  return n

def wait(dispatch, url, index): # pragma: no cover
  
  resp = requests.get('{}?wait=true&recursive=true&waitIndex={}'.format(
    url,
    index
  )).json()
  node =  resp['node']
  dispatch(resp['action'], node)

  return  node['modifiedIndex'] + 1

def guard(func, keys, value_dict):
  """
  Given a function and a list of keys invoke
  the function only if all the keys are present
  in the dictionary.

  >>> f = lambda d: d

  >>> guard(f, ['key1'], {'key1': 1})
  {'key1': 1}

  >>> guard(f, ['key1'], {'key2': 1})

  """
  for key in keys:
    if key not in value_dict:
      return None

  return func(value_dict)


def load_template(stream):
  """
  Rerturns a list of tokens from a file like object

  >>> from StringIO import StringIO
  >>> stream = StringIO("I'm a template\\n {a/key/yeah}")
  >>> load_template(stream)
  ["I'm a template\\n ", Key(path='a/key/yeah')]
  """
  return list(tokenize(stream.read()))

def make_template(path):
  """
  >>> from adnauseam import TEST_ROOT
  >>> test_template = os.path.join(TEST_ROOT, 'my.template')
  >>> open(test_template,'w').write('''
  ... Test template: {key1}
  ... x = {key2}
  ... y = {key2}
  ... ''')

  >>> keys, cooked = make_template(test_template) # doctest: +ELLIPSIS
  >>> keys
  ['key1', 'key2', 'key2']
  >>> cooked(dict(key1='Mickey', key2='3.14'))
  '\\nTest template: Mickey\\nx = 3.14\\ny = 3.14\\n'
  """

  tokens = load_template(open(path))
  return keys(tokens), compile(tokens)

def collect(context_map, action, node):
  """
  Given a 
  context_map which looks like {'some path': [dict1, dict2]}
  an action which is either 'set', 'delete', 'expire'
  and a node which represents an update. 
  Update the context map appropriatly

  >>> cm = {'/some/key': [{}]}
  >>> collect(cm, 'set', dict(key='/some/key', value=2))
  >>> cm
  {'/some/key': ({'/some/key': 2},)}

  It collects keys for multiple dictionaries
  >>> cm = {'/some/key': [{}, {}]}
  >>> collect(cm, 'set', dict(key='/some/key', value=2))
  >>> cm
  {'/some/key': ({'/some/key': 2}, {'/some/key': 2})}

  It removes keys for multiple dictionaries
  >>> collect(cm, 'delete', dict(key='/some/key', value=2))
  >>> cm
  {'/some/key': ({}, {})}

  And ignores updates to keys it's not watching
  >>> collect(cm, 'delete', dict(key='/some/unwatched/key', value=200))
  >>> cm
  {'/some/key': ({}, {})}


  """
  key = node['key']

  contexts = context_map.get(key)
  if not contexts:
    return

  if action in ('delete','expire'):
    new = tuple(del_key(c,key) for c in contexts)
  else:
    new = tuple(set_key(c,key, node['value']) for c in contexts)

  context_map[key] = new

def render(outputs):
  """
  Given a list of tuples where each tuple = (path, template(), context)

  Attempt to call the template with the context and the
  results to path if there was any. Otherwise remove
  the path.

  Returns a list of all paths written.

  >>> import adnauseam
  >>> path = os.path.join(adnauseam.TEST_ROOT, 'render_test')

  Here's a function that always returns results
  >>> t = lambda context: 'hi mom'

  Therefore render will return the path
  >>> render([(path, t, {})]) == [path]
  True

  If on the other hand we pass a function that returns None
  it will remove the path
  >>> render([(path, lambda ctx: None, {})]) == [] # doctest: +ELLIPSIS
  removing ...
  True

  """
  created = []

  for path, template, context in outputs:
    output = template(context)
    if output is None:
      if os.path.exists(path):
        print 'removing  {}'.format(path)
        os.remove(path)
    else:
      open(path, 'w').write(output)
      created.append(path)

  return created


def not_running(action, cmd): # pragma: no cover
  if action == 'start':
    print "Starting {}".format(cmd)
    return running, subprocess.Popen(cmd)
  else: # ignore other events
    return (not_running,)

def running(action, cmd, proc): # pragma: no cover
  if action == 'start':
    # reload the 
    print "Restarting {}".format(cmd)
    proc.terminate()
    proc.poll() 
    return running, subprocess.Popen(cmd)
  elif action == 'stop':
    print 'Killing {}'.format(cmd)
    proc.terminate()
    proc.poll()
    return (not_running,)
  else:
    raise RuntimeError('unknown transition {}'.format(action))



def proc_statemachine(state, cmd, *args):
  # State 1: process hasn't started
  while True:
    action = yield
    transition = state(action, cmd, *args)
    state = transition[0]
    args = transition[1:]



def setup(module):
  import tempfile
  module.TEST_ROOT=tempfile.mkdtemp()

def teardown(module):
  import shutil
  shutil.rmtree(module.TEST_ROOT)
  del module.TEST_ROOT

def compile_templates(template_mapping):

  keys_to_context = defaultdict(list)
  outputs = []

  for template_path, output_path in template_mapping.items():
    keys, template = make_template(template_path)
    context = {}
    for key in keys:
      keys_to_context[key].append(context)
    outputs.append((output_path, partial(guard,template,keys),  context))


  print keys_to_context.keys()
  return partial(render, outputs), partial(collect, keys_to_context)

def collect_env(collect):
  # add everything under the environment to env/
  for key,value in os.environ.items():
    collect('set', dict(key='env/' + key,value=value))



if __name__ == "__main__":  # pragma: no cover
  import doctest
  import adnauseam

  setup(adnauseam)
  try:
     doctest.testmod()
  finally:
    teardown(adnauseam)    

