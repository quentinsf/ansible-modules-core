#!/usr/bin/python
# This file is part of Ansible
#
# Ansible is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# Ansible is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with Ansible.  If not, see <http://www.gnu.org/licenses/>.

# This is a DOCUMENTATION stub specific to this module, it extends
# a documentation fragment located in ansible.utils.module_docs_fragments
DOCUMENTATION = '''
---
module: rax_clb_nodes
short_description: add, modify and remove nodes from a Rackspace Cloud Load Balancer
description:
  - Adds, modifies and removes nodes from a Rackspace Cloud Load Balancer
version_added: "1.4"
options:
  address:
    required: false
    description:
      - IP address or domain name of the node
  condition:
    required: false
    choices:
      - enabled
      - disabled
      - draining
    description:
      - Condition for the node, which determines its role within the load
        balancer
  load_balancer_id:
    required: true
    type: integer
    description:
      - Load balancer id
  node_id:
    required: false
    type: integer
    description:
      - Node id
  port:
    required: false
    type: integer
    description:
      - Port number of the load balanced service on the node
  state:
    required: false
    default: "present"
    choices:
      - present
      - absent
    description:
      - Indicate desired state of the node
  type:
    required: false
    choices:
      - primary
      - secondary
    description:
      - Type of node
  wait:
    required: false
    default: "no"
    choices:
      - "yes"
      - "no"
    description:
      - Wait for the load balancer to become active before returning
  wait_timeout:
    required: false
    type: integer
    default: 30
    description:
      - How long to wait before giving up and returning an error
  weight:
    required: false
    description:
      - Weight of node
author: Lukasz Kawczynski
extends_documentation_fragment: rackspace
'''

EXAMPLES = '''
# Add a new node to the load balancer
- local_action:
    module: rax_clb_nodes
    load_balancer_id: 71
    address: 10.2.2.3
    port: 80
    condition: enabled
    type: primary
    wait: yes
    credentials: /path/to/credentials

# Drain connections from a node
- local_action:
    module: rax_clb_nodes
    load_balancer_id: 71
    node_id: 410
    condition: draining
    wait: yes
    credentials: /path/to/credentials

# Remove a node from the load balancer
- local_action:
    module: rax_clb_nodes
    load_balancer_id: 71
    node_id: 410
    state: absent
    wait: yes
    credentials: /path/to/credentials
'''

try:
    import pyrax
    HAS_PYRAX = True
except ImportError:
    HAS_PYRAX = False


def _activate_virtualenv(path):
    path = os.path.expanduser(path)
    activate_this = os.path.join(path, 'bin', 'activate_this.py')
    execfile(activate_this, dict(__file__=activate_this))


def _get_node(lb, node_id=None, address=None, port=None):
    """Return a matching node"""
    for node in getattr(lb, 'nodes', []):
        match_list = []
        if node_id is not None:
            match_list.append(getattr(node, 'id', None) == node_id)
        if address is not None:
            match_list.append(getattr(node, 'address', None) == address)
        if port is not None:
            match_list.append(getattr(node, 'port', None) == port)

        if match_list and all(match_list):
            return node

    return None


def _is_primary(node):
    """Return True if node is primary and enabled"""
    return (node.type.lower() == 'primary' and
            node.condition.lower() == 'enabled')


def _get_primary_nodes(lb):
    """Return a list of primary and enabled nodes"""
    nodes = []
    for node in lb.nodes:
        if _is_primary(node):
            nodes.append(node)
    return nodes


def main():
    argument_spec = rax_argument_spec()
    argument_spec.update(
        dict(
            address=dict(),
            condition=dict(choices=['enabled', 'disabled', 'draining']),
            load_balancer_id=dict(required=True, type='int'),
            node_id=dict(type='int'),
            port=dict(type='int'),
            state=dict(default='present', choices=['present', 'absent']),
            type=dict(choices=['primary', 'secondary']),
            virtualenv=dict(),
            wait=dict(default=False, type='bool'),
            wait_timeout=dict(default=30, type='int'),
            weight=dict(type='int'),
        )
    )

    module = AnsibleModule(
        argument_spec=argument_spec,
        required_together=rax_required_together(),
    )

    if not HAS_PYRAX:
        module.fail_json(msg='pyrax is required for this module')

    address = module.params['address']
    condition = (module.params['condition'] and
                 module.params['condition'].upper())
    load_balancer_id = module.params['load_balancer_id']
    node_id = module.params['node_id']
    port = module.params['port']
    state = module.params['state']
    typ = module.params['type'] and module.params['type'].upper()
    virtualenv = module.params['virtualenv']
    wait = module.params['wait']
    wait_timeout = module.params['wait_timeout'] or 1
    weight = module.params['weight']

    if virtualenv:
        try:
            _activate_virtualenv(virtualenv)
        except IOError, e:
            module.fail_json(msg='Failed to activate virtualenv %s (%s)' % (
                                 virtualenv, e))

    setup_rax_module(module, pyrax)

    if not pyrax.cloud_loadbalancers:
        module.fail_json(msg='Failed to instantiate client. This '
                             'typically indicates an invalid region or an '
                             'incorrectly capitalized region name.')

    try:
        lb = pyrax.cloud_loadbalancers.get(load_balancer_id)
    except pyrax.exc.PyraxException, e:
        module.fail_json(msg='%s' % e.message)

    node = _get_node(lb, node_id, address, port)

    result = rax_clb_node_to_dict(node)

    if state == 'absent':
        if not node:  # Removing a non-existent node
            module.exit_json(changed=False, state=state)

        # The API detects this as well but currently pyrax does not return a
        # meaningful error message
        if _is_primary(node) and len(_get_primary_nodes(lb)) == 1:
            module.fail_json(
                msg='At least one primary node has to be enabled')

        try:
            lb.delete_node(node)
            result = {}
        except pyrax.exc.NotFound:
            module.exit_json(changed=False, state=state)
        except pyrax.exc.PyraxException, e:
            module.fail_json(msg='%s' % e.message)
    else:  # present
        if not node:
            if node_id:  # Updating a non-existent node
                msg = 'Node %d not found' % node_id
                if lb.nodes:
                    msg += (' (available nodes: %s)' %
                            ', '.join([str(x.id) for x in lb.nodes]))
                module.fail_json(msg=msg)
            else:  # Creating a new node
                try:
                    node = pyrax.cloudloadbalancers.Node(
                        address=address, port=port, condition=condition,
                        weight=weight, type=typ)
                    resp, body = lb.add_nodes([node])
                    result.update(body['nodes'][0])
                except pyrax.exc.PyraxException, e:
                    module.fail_json(msg='%s' % e.message)
        else:  # Updating an existing node
            mutable = {
                'condition': condition,
                'type': typ,
                'weight': weight,
            }

            for name, value in mutable.items():
                if value is None or value == getattr(node, name):
                    mutable.pop(name)

            if not mutable:
                module.exit_json(changed=False, state=state, node=result)

            try:
                # The diff has to be set explicitly to update node's weight and
                # type; this should probably be fixed in pyrax
                lb.update_node(node, diff=mutable)
                result.update(mutable)
            except pyrax.exc.PyraxException, e:
                module.fail_json(msg='%s' % e.message)

    if wait:
        pyrax.utils.wait_until(lb, "status", "ACTIVE", interval=1,
                               attempts=wait_timeout)
        if lb.status != 'ACTIVE':
            module.fail_json(
                msg='Load balancer not active after %ds (current status: %s)' %
                    (wait_timeout, lb.status.lower()))

    kwargs = {'node': result} if result else {}
    module.exit_json(changed=True, state=state, **kwargs)


# import module snippets
from ansible.module_utils.basic import *
from ansible.module_utils.rax import *

### invoke the module
main()
