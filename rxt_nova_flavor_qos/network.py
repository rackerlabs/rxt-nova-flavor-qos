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

import copy

from oslo_log import log as logging
from oslo_utils import uuidutils

from nova.i18n import _
from nova.network import constants as nova_constants
from nova.network import neutron

from rxt_nova_flavor_qos import constants


LOG = logging.getLogger(__name__)


class FlavorQosNeutronAPI(neutron.API):
    """Publish a resize's target flavor without changing Nova semantics."""

    def migrate_instance_finish(
            self, context, instance, migration, provider_mappings):
        result = super().migrate_instance_finish(
            context, instance, migration, provider_mappings)

        try:
            self._publish_target_flavor(context, instance, migration)
        except Exception:
            # This adapter must never turn a successful stock Nova network
            # migration into a failed resize.
            LOG.exception(
                "Unable to publish target flavor after network migration for "
                "instance %(instance_uuid)s migration %(migration_uuid)s; "
                "continuing with stock Nova behavior",
                {
                    "instance_uuid": getattr(instance, "uuid", None),
                    "migration_uuid": getattr(migration, "uuid", None),
                },
                instance=instance,
            )

        return result

    def _publish_target_flavor(self, context, instance, migration):
        old_type_id = getattr(migration, "old_instance_type_id", None)
        new_type_id = getattr(migration, "new_instance_type_id", None)
        if old_type_id == new_type_id:
            return

        instance_uuid = str(instance.uuid)
        flavor_id = self._get_public_flavor_id(instance)
        migration_uuid = self._get_migration_uuid(migration)
        client = neutron.get_client(context, admin=True)
        ports = client.list_ports(
            device_id=instance_uuid,
            tenant_id=instance.project_id,
        ).get("ports", [])

        for port in ports:
            self._publish_port_target_flavor(
                client, port, instance, flavor_id, instance_uuid,
                migration_uuid)

    def _publish_port_target_flavor(
            self, client, port, instance, flavor_id, instance_uuid,
            migration_uuid):
        port_id = port.get("id")
        try:
            profile = copy.deepcopy(neutron.get_binding_profile(port))
            if not isinstance(profile, dict):
                profile = {}

            if (
                str(profile.get(constants.NOVA_FLAVOR_ID, "")) == flavor_id
                and str(profile.get(
                    constants.NOVA_FLAVOR_INSTANCE_UUID, "")) == instance_uuid
                and str(profile.get(
                    constants.NOVA_FLAVOR_MIGRATION_UUID, ""))
                == migration_uuid
            ):
                return

            profile[constants.NOVA_FLAVOR_ID] = flavor_id
            profile[constants.NOVA_FLAVOR_INSTANCE_UUID] = instance_uuid
            profile[constants.NOVA_FLAVOR_MIGRATION_UUID] = migration_uuid
            client.update_port(
                port_id,
                {
                    "port": {
                        nova_constants.BINDING_PROFILE: profile,
                    },
                },
            )
            LOG.info(
                "Published target flavor %(flavor_id)s for instance "
                "%(instance_uuid)s on port %(port_id)s after migration "
                "%(migration_uuid)s",
                {
                    "flavor_id": flavor_id,
                    "instance_uuid": instance_uuid,
                    "port_id": port_id,
                    "migration_uuid": migration_uuid,
                },
                instance=instance,
            )
        except Exception:
            LOG.exception(
                "Unable to publish target flavor %(flavor_id)s for instance "
                "%(instance_uuid)s on port %(port_id)s after migration "
                "%(migration_uuid)s; continuing with stock Nova behavior for "
                "this port",
                {
                    "flavor_id": flavor_id,
                    "instance_uuid": instance_uuid,
                    "port_id": port_id,
                    "migration_uuid": migration_uuid,
                },
                instance=instance,
            )

    @staticmethod
    def _get_public_flavor_id(instance):
        flavor = instance.flavor
        flavor_id = getattr(flavor, "flavorid", None)
        if flavor_id is None and isinstance(flavor, dict):
            flavor_id = flavor.get("flavorid")
        if flavor_id is None or not str(flavor_id).strip():
            raise ValueError(_(
                "instance target flavor has no public flavor ID"))
        return str(flavor_id).strip()

    @staticmethod
    def _get_migration_uuid(migration):
        migration_uuid = getattr(migration, "uuid", None)
        migration_uuid = (str(migration_uuid).strip()
                          if migration_uuid is not None else "")
        if not uuidutils.is_uuid_like(migration_uuid):
            raise ValueError(_("migration has no valid UUID"))
        return migration_uuid
