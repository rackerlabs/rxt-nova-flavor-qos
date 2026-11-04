# RXT Nova Flavor QoS

Out-of-tree Nova compute adapter for resize-safe flavor-based Neutron QoS.
It complements the `neutron-flavor-qos` service plugin by publishing the
target Nova flavor in a port's binding profile after Nova performs its normal
resize binding update.

The adapter is intentionally fail-open. Its work never makes an otherwise
successful Nova resize fail. If the adapter cannot list or update a port, it
logs the failure and leaves the deployment with stock Nova behavior.

## Why this exists

During a flavor-changing resize, Nova updates Neutron before it persists the
new flavor on the instance record. A Neutron callback that reads the server at
that moment can therefore see the old flavor. This adapter uses the target
flavor already present on Nova's in-memory instance and publishes it through
the port binding profile:

```json
{
  "binding:profile": {
    "nova_flavor_id": "d99ebe55-988d-41d5-a387-4fce42aadb68",
    "nova_flavor_instance_uuid": "2b3b27f3-e7f4-46f8-a48a-f999b1ad4317"
  }
}
```

The companion instance UUID prevents a marker retained on a detached port
from being trusted after that port is attached to a different server.

## Execution order

For a flavor-changing resize or resize revert:

1. Stock Nova performs `migrate_instance_finish()`.
2. The adapter lists the instance's Neutron ports.
3. It merges the target public flavor ID and instance UUID into each binding
   profile without changing unrelated profile fields.
4. Each successful profile update causes the Neutron service plugin to run
   its normal `PORT AFTER_UPDATE` reconciliation.
5. Failures are logged per port and are not raised into Nova.

Calling stock Nova first is deliberate. If stock network migration fails, its
exception is preserved and no adapter update is attempted. If only the
adapter fails, Nova continues exactly as it would without this package.

## Installation

Install this package into the same Python environment as `nova-compute`:

```bash
python -m pip install /path/to/rxt-nova-flavor-qos
```

Run the packaged compute entry point instead of the stock executable:

```bash
nova-flavor-qos-compute --config-file /etc/nova/nova.conf
```

The wrapper delegates process initialization to `nova.cmd.compute.main` and
only selects `rxt_nova_flavor_qos.compute.FlavorQosComputeManager` as the
compute service manager. Nova API, conductor, and scheduler services are not
changed.

Rollback consists of restoring the stock `nova-compute` command and restarting
the compute service. Existing binding-profile markers are ignored by stock
Nova.

## Compatibility

The initial compatibility target is Nova `stable/2026.1`. The adapter relies
on these Nova interfaces:

- `nova.compute.manager.ComputeManager`
- `nova.network.neutron.API.migrate_instance_finish`
- `nova.network.neutron.get_client`
- `nova.network.neutron.get_binding_profile`
- `nova.service.SERVICE_MANAGERS`

These imports are intentionally isolated in a small package and covered by
unit and import-compatibility tests.

## Development

Set `NOVA_SOURCE` to a Nova checkout when running tox if Nova is not installed
in the test environment:

```bash
NOVA_SOURCE=/path/to/nova tox -e py3
```

For a pre-existing development virtual environment:

```bash
PYTHONPATH=/path/to/nova:. python -m unittest discover tests/unit
```

