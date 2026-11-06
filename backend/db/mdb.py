"""MongoDB access for the backend: two databases on one cluster.

The data is split across two databases and the backend is the only component allowed to
hold both (the agents each hold one):

* the **insurance** database  — members, policies, plans, claims, the shared authorization
  trace (`audit_log`) and the Insurance Agent's reasoning text (`admin_reasoning`);
* the **clinical** database   — clinical profiles, dispense history, guidelines and the
  Care-Coordination Agent's reasoning text (`clinical_reasoning`).

Database names always come from the environment, never from code:

    MONGODB_URI          one connection string for both
    INSURANCE_DATABASE   the insurance database (falls back to DATABASE_NAME, so an existing
                         single-database deployment keeps its insurance routes working)
    CLINICAL_DATABASE    the clinical database

A missing name raises `ConfigurationError` when the connector is first requested, not at
import, so a half-configured deployment still starts and serves every route that does not
need the missing database. `main.py` turns the error into a 503 that names the variable.
"""

import os
from functools import lru_cache

from pymongo import MongoClient
from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv()


class ConfigurationError(RuntimeError):
    """A required environment variable is not set."""


@lru_cache(maxsize=4)
def _client(uri: str, appname: str) -> MongoClient:
    """One client (and connection pool) per connection string, shared by both databases."""
    return MongoClient(uri, appname=appname)


class MongoDBConnector:
    """A handle on one database.

    Attributes:
        uri (str): The connection string URI for the MongoDB cluster.
        database_name (str): The name of the database to connect to.
        appname (str): The name of the application connecting to the database.
    """

    def __init__(self, uri=None, database_name=None, appname=None):
        self.uri = uri or os.getenv("MONGODB_URI")
        self.database_name = database_name
        self.appname = appname or os.getenv("APP_NAME")
        if not self.uri:
            raise ConfigurationError("MONGODB_URI is not set.")
        if not self.database_name:
            raise ConfigurationError("A database name is required.")
        self.client = _client(self.uri, self.appname or "")
        self.db = self.client[self.database_name]

    def get_collection(self, collection_name):
        """Retrieve a collection."""
        if not collection_name:
            raise ValueError("Collection name must be provided.")
        return self.db[collection_name]

    def insert_one(self, collection_name, document):
        return self.get_collection(collection_name).insert_one(document).inserted_id

    def insert_many(self, collection_name, documents):
        return self.get_collection(collection_name).insert_many(documents).inserted_ids

    def find(self, collection_name, query=None, projection=None):
        return list(self.get_collection(collection_name).find(query or {}, projection))

    def update_one(self, collection_name, query, update, upsert=False):
        return self.get_collection(collection_name).update_one(query, update, upsert=upsert).modified_count

    def update_many(self, collection_name, query, update, upsert=False):
        return self.get_collection(collection_name).update_many(query, update, upsert=upsert).modified_count

    def delete_one(self, collection_name, query):
        return self.get_collection(collection_name).delete_one(query).deleted_count

    def delete_many(self, collection_name, query):
        return self.get_collection(collection_name).delete_many(query).deleted_count

    def close(self):
        """Close the underlying MongoClient and its connection pool."""
        self.client.close()


def _database_name(*env_names: str) -> str:
    for name in env_names:
        value = os.getenv(name, "").strip()
        if value:
            return value
    raise ConfigurationError(
        f"{' or '.join(env_names)} is not set. Declare it in .env / the deployment config."
    )


@lru_cache(maxsize=1)
def get_insurance_connector() -> MongoDBConnector:
    """The process-wide connector for the insurance database.

    Also the FastAPI dependency the insurance-side routes inject, so tests can swap it with
    `app.dependency_overrides[get_insurance_connector] = ...`. `lru_cache` does not memoise
    an exception, so a later call retries once the variable is present.
    """
    return MongoDBConnector(database_name=_database_name("INSURANCE_DATABASE", "DATABASE_NAME"))


@lru_cache(maxsize=1)
def get_clinical_connector() -> MongoDBConnector:
    """The process-wide connector for the clinical database. A FastAPI dependency like
    `get_insurance_connector`."""
    return MongoDBConnector(database_name=_database_name("CLINICAL_DATABASE"))


def close_connector() -> None:
    """Dispose the cached connectors. Call on application shutdown."""
    for getter in (get_insurance_connector, get_clinical_connector):
        if getter.cache_info().currsize:
            getter().close()
            getter.cache_clear()
