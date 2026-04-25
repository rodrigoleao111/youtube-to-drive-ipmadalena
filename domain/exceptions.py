"""
Hierarquia de exceções do domínio.

Todas as exceções do projeto herdam de IPMadalenaError para facilitar
o tratamento genérico em camadas superiores (UI, CLI).

Nota: OperacaoCancelada também é definida em baixar_audio.py por
compatibilidade retroativa — durante a migração, ambas as definições
coexistem. Ao final da refatoração, apenas esta será usada.
"""


class IPMadalenaError(Exception):
    """Exceção base para todos os erros do projeto."""


class DomainError(IPMadalenaError):
    """Erro de regra de negócio (validação, estado inválido, etc.)."""


class OperacaoCancelada(IPMadalenaError):
    """
    Levantada quando o usuário cancela uma operação em andamento.

    Usada como sinal de controle de fluxo — não representa um erro
    de sistema, mas uma interrupção intencional.
    """


class VideoNaoEncontrado(DomainError):
    """Nenhum vídeo encontrado para a data solicitada."""


class SegmentoInvalido(DomainError):
    """
    Trecho de vídeo inválido.

    Exemplos:
      - Fim anterior ao início
      - Formato HH:MM:SS inválido
      - Início e fim idênticos
    """


class ConfiguracaoInvalida(DomainError):
    """Configuração ausente ou com valor inválido."""
