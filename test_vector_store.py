

from scripts.create_vector_store_for_catalog import ForzaCatalogVectorStore

def test_vector_store():
    vectorstore = ForzaCatalogVectorStore()
    vectorstore.run("data/forza.json", collection_name="forza_web_pages")


if __name__ == "__main__":
    test_vector_store()