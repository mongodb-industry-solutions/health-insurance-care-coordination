"""Generic repository built on top of the shared MongoDBConnector.

The repository pattern keeps data-access logic in one place so agents and tools
never touch pymongo directly. Concrete repositories bind to a single collection
and inherit these idempotent CRUD/seed helpers.

**Lookups resolve on business keys, not `_id`.** In this data model `_id` is a
MongoDB-assigned ObjectId that is never set manually and never used as a join
key: every cross-object reference joins on a business key (`memberId`,
`policyId`, `planId`, `claimId`, `traceId`). Concrete repositories declare their
`business_key` and callers use `get_by_key`.

`_id` is deliberately still returned by reads, because `upsert` keys on it and
several services do read-modify-write. Projecting it out would leave those writes
without a key and insert duplicates instead of replacing.
"""

from db.mdb import MongoDBConnector


class Repository:
    """Generic CRUD helpers bound to a single collection."""

    collection_name: str = ""
    # Field that lookups resolve on. Overridden per collection; `_id` only where
    # the collection genuinely has no separate business key.
    business_key: str = "_id"

    def __init__(self, connector: MongoDBConnector):
        """`connector` is required: a repository belongs to exactly one database, and which
        one is visible at the call site (`get_insurance_connector()` or
        `get_clinical_connector()`), never defaulted."""
        if not self.collection_name:
            raise ValueError("Subclasses must set `collection_name`.")
        self.connector = connector

    @property
    def collection(self):
        return self.connector.get_collection(self.collection_name)

    def get_by_key(self, key_value):
        """Fetch one document by its business key. The default lookup."""
        return self.collection.find_one({self.business_key: key_value})

    def get_by_id(self, doc_id):
        """Fetch by raw `_id`. Only for collections whose `_id` IS the business key."""
        return self.collection.find_one({"_id": doc_id})

    def find(self, query=None, projection=None):
        return list(self.collection.find(query or {}, projection))

    def insert(self, document):
        return self.collection.insert_one(document).inserted_id

    def insert_many(self, documents):
        if not documents:
            return []
        return self.collection.insert_many(documents).inserted_ids

    def upsert(self, document):
        """Replace-by-business-key upsert. Makes re-seeding idempotent.

        Keyed on `business_key`, not `_id`: the seed files carry no `_id` (MongoDB assigns
        an ObjectId on insert), so an upsert keyed on `_id` would raise `KeyError` or
        insert a duplicate beside the document already there.
        """
        key = document[self.business_key]
        self.collection.replace_one({self.business_key: key}, document, upsert=True)
        return key

    def upsert_many(self, documents):
        return [self.upsert(doc) for doc in documents]

    def delete_by(self, query):
        """Delete every document matching a query. Returns the delete count."""
        return self.collection.delete_many(query).deleted_count

    def delete_all(self):
        """Clear the collection. Used to reset demo data before a fresh seed."""
        return self.collection.delete_many({}).deleted_count
