"""Generic repository built on top of the shared MongoDBConnector.

The repository pattern keeps data-access logic in one place so agents and tools
never touch pymongo directly. Concrete repositories bind to a single collection
and inherit these idempotent CRUD/seed helpers.
"""

from db.mdb import MongoDBConnector


class Repository:
    """Generic CRUD helpers bound to a single collection."""

    collection_name: str = ""

    def __init__(self, connector: MongoDBConnector | None = None):
        if not self.collection_name:
            raise ValueError("Subclasses must set `collection_name`.")
        self.connector = connector or MongoDBConnector()

    @property
    def collection(self):
        return self.connector.get_collection(self.collection_name)

    def get_by_id(self, doc_id):
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
        """Replace-by-_id upsert. Makes re-seeding idempotent."""
        doc_id = document["_id"]
        self.collection.replace_one({"_id": doc_id}, document, upsert=True)
        return doc_id

    def upsert_many(self, documents):
        return [self.upsert(doc) for doc in documents]

    def delete_by(self, query):
        """Delete every document matching a query. Returns the delete count."""
        return self.collection.delete_many(query).deleted_count

    def delete_all(self):
        """Clear the collection. Used to reset demo data before a fresh seed."""
        return self.collection.delete_many({}).deleted_count
