"""The files ``tau-router ext-args`` gives Tau 0.13. Each holds only an absolute import of its ``register``.

Tau 0.13 loads an extension by file path under a synthetic module name, so a module here runs
twice if anything also imports it by its real name. Keeping the code in ``tau_router.router`` and
``tau_router.planner`` means it, and its state, exist once.
"""
