"""adlfs and the Azure SDK, which ``AzureDataLakeGen2Operation`` needs: in a
module of their own, imported when an operation first needs them (see
``operations._azure``), so that the plugin loads without them (they are its
"full" extra)."""

from adlfs import AzureBlobFileSystem
from azure.core import MatchConditions
from azure.storage.blob.aio import BlobServiceClient
from azure.storage.filedatalake.aio import DataLakeServiceClient

__all__ = [
    "AzureBlobFileSystem",
    "BlobServiceClient",
    "DataLakeServiceClient",
    "MatchConditions",
]
