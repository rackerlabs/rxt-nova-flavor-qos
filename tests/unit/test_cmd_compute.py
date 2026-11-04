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

import unittest
from unittest import mock

from rxt_nova_flavor_qos.cmd import compute


class ComputeCommandTestCase(unittest.TestCase):
    def test_main_selects_adapter_manager_and_delegates_to_nova(self):
        from nova import service

        original = service.SERVICE_MANAGERS["nova-compute"]
        self.addCleanup(
            service.SERVICE_MANAGERS.__setitem__, "nova-compute", original)

        with mock.patch.object(compute.nova_compute, "main") as nova_main:
            compute.main()

        self.assertEqual(
            compute.COMPUTE_MANAGER,
            service.SERVICE_MANAGERS["nova-compute"],
        )
        nova_main.assert_called_once_with()
