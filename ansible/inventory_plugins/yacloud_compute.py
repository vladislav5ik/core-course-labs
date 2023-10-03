# GNU General Public License v3.0+ (see COPYING or https://www.gnu.org/licenses/gpl-3.0.txt) # noqa: E501

from __future__ import absolute_import, division, print_function

__metaclass__ = type

DOCUMENTATION = """
    name: yacloud_compute
    plugin_type: inventory
    short_description: Yandex.Cloud compute inventory source
    requirements:
        - yandexcloud
    extends_documentation_fragment:
        - inventory_cache
        - constructed
    description:
        - Get inventory hosts from Yandex Cloud
        - Uses a YAML configuration file that ends with C(yacloud_compute.(yml|yaml)). # noqa: E501
    options:
        plugin:
            description: Token that ensures this is a source file for the plugin. # noqa: E501
            required: True
            choices: ['yacloud_compute']
        yacloud_token:
            description: Oauth token for yacloud connection
        yacloud_token_file:
            description: File with oauth token for yacloud connection
        yacloud_clouds:
            description: Names of clouds to get hosts from
            type: list
            default: []
        yacloud_folders:
            description: Names of folders to get hosts from
            type: list
            default: []
        yacloud_group_label:
            description: VM's label used for group assignment
            type: string
            default: ""

"""

EXAMPLES = """
"""

from ansible.errors import AnsibleError  # noqa: E402
from ansible.module_utils._text import to_native  # noqa: E402
from ansible.plugins.inventory import (  # noqa: E501,E402
    BaseInventoryPlugin,
    Cacheable,
    Constructable,
)
from ansible.utils.display import Display  # noqa: E402

try:
    import yandexcloud
    from google.protobuf.json_format import MessageToDict
    from yandex.cloud.compute.v1.instance_service_pb2 import (  # noqa: E501
        ListInstancesRequest,
    )
    from yandex.cloud.compute.v1.instance_service_pb2_grpc import (  # noqa: E501
        InstanceServiceStub,
    )
    from yandex.cloud.resourcemanager.v1.cloud_service_pb2 import (  # noqa: E501
        ListCloudsRequest,
    )
    from yandex.cloud.resourcemanager.v1.cloud_service_pb2_grpc import (  # noqa: E501
        CloudServiceStub,
    )
    from yandex.cloud.resourcemanager.v1.folder_service_pb2 import (  # noqa: E501
        ListFoldersRequest,
    )
    from yandex.cloud.resourcemanager.v1.folder_service_pb2_grpc import (
        FolderServiceStub,
    )
except ImportError:
    raise AnsibleError(
        "The yacloud dynamic inventory plugin requires yandexcloud"
    )  # noqa: E501

display = Display()


class InventoryModule(BaseInventoryPlugin, Constructable, Cacheable):
    NAME = "yacloud_compute"

    def verify_file(self, path):
        if super(InventoryModule, self).verify_file(path):
            if path.endswith(("yacloud_compute.yml", "yacloud_compute.yaml")):
                return True
        display.debug(
            "yacloud_compute inventory filename must end with 'yacloud_compute.yml' or 'yacloud_compute.yaml'"  # noqa: E501
        )
        return False

    def _get_ip_for_instance(self, instance):
        interfaces = instance["networkInterfaces"]
        for interface in interfaces:
            address = interface["primaryV4Address"]
            if address:
                if address.get("oneToOneNat"):
                    return address["oneToOneNat"]["address"]
                else:
                    return address["address"]
        return None

    def _get_clouds(self):
        all_clouds = MessageToDict(
            self.cloud_service.List(ListCloudsRequest())
        )[  # noqa: E501
            "clouds"
        ]
        if self.get_option("yacloud_clouds"):
            all_clouds[:] = [
                x
                for x in all_clouds
                if x["name"] in self.get_option("yacloud_clouds")  # noqa: E501
            ]
        self.clouds = all_clouds

    def _get_folders(self):
        all_folders = []
        for cloud in self.clouds:
            cid = cloud["id"]
            all_folders += MessageToDict(
                self.folder_service.List(ListFoldersRequest(cloud_id=cid))
            )["folders"]

        if self.get_option("yacloud_folders"):
            all_folders[:] = [
                x
                for x in all_folders
                if x["name"] in self.get_option("yacloud_folders")
            ]

        self.folders = all_folders

    def _get_all_hosts(self):
        self.hosts = []
        for folder in self.folders:
            hosts = self.instance_service.List(
                ListInstancesRequest(folder_id=folder["id"])
            )
            dict_ = MessageToDict(hosts)

            if dict_:
                self.hosts += dict_["instances"]

    def _init_client(self):
        file = self.get_option("yacloud_token_file")
        if file is not None:
            token = open(file).read().strip()
        else:
            token = self.get_option("yacloud_token")
        if not token:
            raise AnsibleError(
                "token it empty."
                + "provide either `yacloud_token_file` or `yacloud_token`"
            )
        sdk = yandexcloud.SDK(token=token)

        self.instance_service = sdk.client(InstanceServiceStub)
        self.folder_service = sdk.client(FolderServiceStub)
        self.cloud_service = sdk.client(CloudServiceStub)

    def _process_hosts(self):
        group_label = str(self.get_option("yacloud_group_label"))

        for instance in self.hosts:
            if group_label and group_label in instance["labels"]:
                group = instance["labels"][group_label]
            else:
                group = "yacloud"

            self.inventory.add_group(group=group)
            if instance["status"] == "RUNNING":
                ip = self._get_ip_for_instance(instance)
                if ip:
                    self.inventory.add_host(instance["name"], group=group)
                    self.inventory.set_variable(
                        instance["name"], "ansible_host", to_native(ip)
                    )

    def parse(self, inventory, loader, path, cache=True):
        super(InventoryModule, self).parse(inventory, loader, path)

        self._read_config_data(path)
        self._init_client()

        self._get_clouds()
        self._get_folders()

        self._get_all_hosts()
        self._process_hosts()
