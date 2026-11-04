# Licensed under the Apache License, Version 2.0 (the "License"); you may
# not use this file except in compliance with the License. You may obtain
# a copy of the License at
#
#      http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS, WITHOUT
# WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied. See the
# License for the specific language governing permissions and limitations
# under the License.

from types import SimpleNamespace
import unittest
from unittest import mock

from nova.network import constants as nova_constants
from nova.network import neutron

from rxt_nova_flavor_qos import constants
from rxt_nova_flavor_qos import network


INSTANCE_UUID = "2b3b27f3-e7f4-46f8-a48a-f999b1ad4317"
FLAVOR_ID = "d99ebe55-988d-41d5-a387-4fce42aadb68"


class FlavorQosNeutronAPITestCase(unittest.TestCase):
    def setUp(self):
        super().setUp()
        self.api = network.FlavorQosNeutronAPI()
        self.context = mock.Mock()
        self.instance = SimpleNamespace(
            uuid=INSTANCE_UUID,
            project_id="project-id",
            flavor=SimpleNamespace(flavorid=FLAVOR_ID),
        )
        self.migration = SimpleNamespace(
            uuid="migration-id",
            old_instance_type_id=1,
            new_instance_type_id=2,
        )
        self.client = mock.Mock()
        self.client.list_ports.return_value = {"ports": []}

    def _finish(self, parent_return="parent-result"):
        parent = mock.patch.object(
            neutron.API,
            "migrate_instance_finish",
            return_value=parent_return,
        )
        get_client = mock.patch.object(
            neutron, "get_client", return_value=self.client)
        with parent as parent_finish, get_client as client_factory:
            result = self.api.migrate_instance_finish(
                self.context, self.instance, self.migration, {"mapping": []})
        return result, parent_finish, client_factory

    def test_updates_profile_after_stock_network_migration(self):
        events = []
        port = {
            "id": "port-1",
            "binding:profile": {"allocation": "rp-uuid"},
        }
        self.client.list_ports.return_value = {"ports": [port]}

        def parent_finish(*args, **kwargs):
            events.append("stock")
            return "parent-result"

        def update_port(*args, **kwargs):
            events.append("marker")

        self.client.update_port.side_effect = update_port
        with mock.patch.object(
                neutron.API, "migrate_instance_finish",
                side_effect=parent_finish) as parent:
            with mock.patch.object(
                    neutron, "get_client", return_value=self.client):
                result = self.api.migrate_instance_finish(
                    self.context, self.instance, self.migration, {})

        self.assertEqual("parent-result", result)
        self.assertEqual(["stock", "marker"], events)
        parent.assert_called_once()
        self.client.update_port.assert_called_once_with(
            "port-1",
            {
                "port": {
                    nova_constants.BINDING_PROFILE: {
                        "allocation": "rp-uuid",
                        constants.NOVA_FLAVOR_ID: FLAVOR_ID,
                        constants.NOVA_FLAVOR_INSTANCE_UUID: INSTANCE_UUID,
                    },
                },
            },
        )
        self.assertEqual(
            {"allocation": "rp-uuid"}, port["binding:profile"])

    def test_same_flavor_migration_performs_no_adapter_calls(self):
        self.migration.new_instance_type_id = 1

        result, parent, client_factory = self._finish()

        self.assertEqual("parent-result", result)
        parent.assert_called_once()
        client_factory.assert_not_called()

    def test_current_marker_is_not_rewritten(self):
        self.client.list_ports.return_value = {
            "ports": [{
                "id": "port-1",
                "binding:profile": {
                    constants.NOVA_FLAVOR_ID: FLAVOR_ID,
                    constants.NOVA_FLAVOR_INSTANCE_UUID: INSTANCE_UUID,
                },
            }],
        }

        self._finish()

        self.client.update_port.assert_not_called()

    def test_port_failure_does_not_block_other_ports_or_nova(self):
        self.client.list_ports.return_value = {
            "ports": [
                {"id": "port-1", "binding:profile": {}},
                {"id": "port-2", "binding:profile": {}},
            ],
        }
        self.client.update_port.side_effect = [
            RuntimeError("port failure"), None]

        result, parent, unused = self._finish()

        self.assertEqual("parent-result", result)
        parent.assert_called_once()
        self.assertEqual(2, self.client.update_port.call_count)

    def test_list_failure_returns_stock_result(self):
        self.client.list_ports.side_effect = RuntimeError("neutron down")

        result, parent, unused = self._finish()

        self.assertEqual("parent-result", result)
        parent.assert_called_once()

    def test_missing_public_flavor_id_returns_stock_result(self):
        self.instance.flavor.flavorid = ""

        result, parent, client_factory = self._finish()

        self.assertEqual("parent-result", result)
        parent.assert_called_once()
        client_factory.assert_not_called()

    def test_stock_network_failure_is_preserved_and_skips_adapter(self):
        with mock.patch.object(
                neutron.API, "migrate_instance_finish",
                side_effect=RuntimeError("stock failure")):
            with mock.patch.object(neutron, "get_client") as client_factory:
                self.assertRaises(
                    RuntimeError,
                    self.api.migrate_instance_finish,
                    self.context,
                    self.instance,
                    self.migration,
                    {},
                )

        client_factory.assert_not_called()

    def test_dict_flavor_is_supported(self):
        self.instance.flavor = {"flavorid": "custom.flavor"}

        result, parent, unused = self._finish()

        self.assertEqual("parent-result", result)
        parent.assert_called_once()
        self.client.list_ports.assert_called_once_with(
            device_id=INSTANCE_UUID,
            tenant_id="project-id",
        )
