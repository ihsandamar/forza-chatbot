from src.graphs.base_graph import BaseGraph
from src.graphs.graph_repository import GraphRepository
from src.graphs.supervisor.graph import create_supervisor_graph
from src.models.models import LLM
from src.services.config_loader import ConfigLoader


# TODO: Add Dynamic Module Discovery and Loading  

def graph(name: str) -> BaseGraph:
    """
    Returns a graph object based on the specified name.
    
    :param name: Name of the graph
    :return: Graph object
    :rtype: MainGraph
    """

    config = ConfigLoader.load_config()
    OPENAI_API_KEY = config.llm.api_key

    llm = LLM(model="gpt-4o-mini", temperature=0, api_key=OPENAI_API_KEY)
    repo = GraphRepository(llm=llm)
    return repo.get_raw(name)




def supervisor_graph():

    config = ConfigLoader.load_config()
    llm = LLM(model=config.llm.model, temperature=config.llm.temperature, api_key=config.llm.api_key)

    return create_supervisor_graph(llm=llm)