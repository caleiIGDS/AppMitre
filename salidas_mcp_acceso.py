"""Dos niveles para el MCP de Gestión, sin sesiones web ni OAuth."""
from tokens_mcp import coincide


def es_admin():
    return coincide('GESTION_MCP_TOKEN_ADMIN')


def nivel():
    if es_admin():
        return 'admin'
    return 'consulta' if coincide('GESTION_MCP_TOKEN_LECTURA') else None
