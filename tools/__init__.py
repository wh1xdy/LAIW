"""
LAIW RAG Tools — search functions for Swedish/EU legal sources.
For use at inference time with the fine-tuned model.
"""
from .legal_search import search_sfs, get_law, search_riksdagen, search_domstol, search_eurlex

__all__ = ["search_sfs", "get_law", "search_riksdagen", "search_domstol", "search_eurlex"]
