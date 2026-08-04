"""Authored game content: the §10.2 requirement grammar, schema, loader and validator.

Deliberately empty of re-exports. ``tracker.content.validate`` is executed as a script by
``make validate-content``, and importing it from this ``__init__`` would make
``python -m tracker.content.validate`` load the module twice — runpy warns about exactly
that. Import from the submodules:

* :mod:`tracker.content.requirements` — the §10.2 grammar
* :mod:`tracker.content.schema` — the Pydantic content models
* :mod:`tracker.content.loader` — :class:`~tracker.content.loader.Content` and parsing
* :mod:`tracker.content.validate` — :func:`~tracker.content.validate.load_and_validate`
"""
