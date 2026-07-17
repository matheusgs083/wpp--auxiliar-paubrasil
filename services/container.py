from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from bot_api.integrations.evolution_client import EvolutionClient, EvolutionConfig
from bot_api.integrations.meta_cloud_client import MetaCloudClient, MetaCloudConfig
from bot_api.security.access_control import AccessControl
from bot_api.security.security_monitor import SecurityMonitor
from bot_api.services.admin_import_job_service import AdminImportJobService
from bot_api.services.boletos_pdf_import_service import BoletosPdfImportService
from bot_api.services.boletos_query_service import BoletosQueryService
from bot_api.services.clientes_score_import_service import ClientesScoreImportService
from bot_api.services.clientes_score_query_service import ClientesScoreQueryService
from bot_api.services.comodatos_import_service import ComodatosImportService
from bot_api.services.comodatos_query_service import ComodatosQueryService
from bot_api.services.critica_operacao_import_service import CriticaOperacaoImportService
from bot_api.services.critica_rn_import_service import CriticaRnImportService
from bot_api.services.critica_rn_query_service import CriticaRnQueryService
from bot_api.services.customer_lookup_flow import CustomerLookupFlow
from bot_api.services.filial_labels import FILIAL_LABELS, set_filial_labels
from bot_api.services.dclientes_import_service import DClientesImportService
from bot_api.services.dclientes_query_service import DClientesQueryService
from bot_api.services.dcondicoes_import_service import DCondicoesImportService
from bot_api.services.documentacao_pendente_import_service import DocumentacaoPendenteImportService
from bot_api.services.documentacao_pendente_query_service import DocumentacaoPendenteQueryService
from bot_api.services.doperacoes_import_service import DOperacoesImportService
from bot_api.services.dprecos_import_service import DPrecosImportService
from bot_api.services.dprodutos_import_service import DProdutosImportService
from bot_api.services.drevendas_import_service import DRevendasImportService
from bot_api.services.dsetores_import_service import DSetoresImportService
from bot_api.services.giro_import_service import GiroImportService
from bot_api.services.giro_query_service import GiroQueryService
from bot_api.services.inadimplencia_import_service import InadimplenciaImportService
from bot_api.services.inadimplencia_query_service import InadimplenciaQueryService
from bot_api.services.payip_payments_service import PayipPaymentsService, build_payip_payments_service
from bot_api.services.prazo_limite_import_service import PrazoLimiteImportService
from bot_api.services.prazo_limite_query_service import PrazoLimiteQueryService
from bot_api.services.produto_cestas_import_service import ProdutoCestasImportService
from bot_api.services.recolha_request_service import RecolhaRequestService


@dataclass(frozen=True)
class AppServices:
    admin_import_job_service: AdminImportJobService
    dclientes_query_service: DClientesQueryService
    clientes_score_query_service: ClientesScoreQueryService
    inadimplencia_query_service: InadimplenciaQueryService
    comodatos_query_service: ComodatosQueryService
    giro_query_service: GiroQueryService
    critica_rn_query_service: CriticaRnQueryService
    critica_rn_pdf_prebuild_service: CriticaRnQueryService
    documentacao_pendente_query_service: DocumentacaoPendenteQueryService
    prazo_limite_query_service: PrazoLimiteQueryService
    boletos_query_service: BoletosQueryService
    dsetores_import_service: DSetoresImportService
    dprecos_import_service: DPrecosImportService
    doperacoes_import_service: DOperacoesImportService
    drevendas_import_service: DRevendasImportService
    dcondicoes_import_service: DCondicoesImportService
    dprodutos_import_service: DProdutosImportService
    produto_cestas_import_service: ProdutoCestasImportService
    boletos_pdf_import_service: BoletosPdfImportService
    boletos_pdf_import_services: dict[str, BoletosPdfImportService]
    dclientes_import_service: DClientesImportService
    clientes_score_import_service: ClientesScoreImportService
    inadimplencia_import_service: InadimplenciaImportService
    comodatos_import_service: ComodatosImportService
    giro_import_service: GiroImportService
    critica_rn_import_service: CriticaRnImportService
    critica_operacao_import_services: dict[str, CriticaOperacaoImportService]
    critica_operacao_admin_service: CriticaOperacaoImportService
    documentacao_pendente_import_service: DocumentacaoPendenteImportService
    prazo_limite_import_service: PrazoLimiteImportService
    recolha_request_service: RecolhaRequestService
    evolution_client: EvolutionClient
    meta_cloud_client: MetaCloudClient
    access_control: AccessControl
    security_monitor: SecurityMonitor
    payip_payments_service: PayipPaymentsService | None
    lookup_flow: CustomerLookupFlow
    filial_labels: dict[str, str]


def build_app_services(settings: Any, *, project_root: Path, logger: logging.Logger) -> AppServices:
    admin_import_job_service = AdminImportJobService(
        database_url=settings.reports_database_url,
        schema=settings.reports_db_schema,
        connect_timeout_seconds=settings.access_database_timeout_seconds,
    )
    dclientes_query_service = DClientesQueryService(
        database_url=settings.reports_runtime_database_url,
        schema=settings.reports_db_schema,
        connect_timeout_seconds=settings.access_database_timeout_seconds,
    )
    clientes_score_query_service = ClientesScoreQueryService(
        database_url=settings.reports_runtime_database_url,
        schema=settings.reports_db_schema,
        connect_timeout_seconds=settings.access_database_timeout_seconds,
    )
    inadimplencia_query_service = InadimplenciaQueryService(
        database_url=settings.reports_runtime_database_url,
        schema=settings.reports_db_schema,
        connect_timeout_seconds=settings.access_database_timeout_seconds,
    )
    comodatos_query_service = ComodatosQueryService(
        database_url=settings.reports_runtime_database_url,
        schema=settings.reports_db_schema,
        connect_timeout_seconds=settings.access_database_timeout_seconds,
    )
    giro_query_service = GiroQueryService(
        database_url=settings.reports_runtime_database_url,
        schema=settings.reports_db_schema,
        connect_timeout_seconds=settings.access_database_timeout_seconds,
    )
    critica_rn_query_service = CriticaRnQueryService(
        database_url=settings.reports_runtime_database_url,
        schema=settings.reports_db_schema,
        connect_timeout_seconds=settings.access_database_timeout_seconds,
    )
    critica_rn_pdf_prebuild_service = CriticaRnQueryService(
        database_url=settings.reports_database_url,
        schema=settings.reports_db_schema,
        connect_timeout_seconds=settings.access_database_timeout_seconds,
    )
    documentacao_pendente_query_service = DocumentacaoPendenteQueryService(
        database_url=settings.reports_runtime_database_url,
        schema=settings.reports_db_schema,
        connect_timeout_seconds=settings.access_database_timeout_seconds,
    )
    prazo_limite_query_service = PrazoLimiteQueryService(
        database_url=settings.reports_runtime_database_url,
        schema=settings.reports_db_schema,
        connect_timeout_seconds=settings.access_database_timeout_seconds,
    )
    boletos_query_service = BoletosQueryService(
        database_url=settings.reports_runtime_database_url,
        schema=settings.reports_db_schema,
        connect_timeout_seconds=settings.access_database_timeout_seconds,
    )
    dsetores_import_service = DSetoresImportService(
        database_url=settings.reports_database_url,
        schema=settings.reports_db_schema,
        connect_timeout_seconds=settings.access_database_timeout_seconds,
    )
    dprecos_import_service = DPrecosImportService(
        database_url=settings.reports_database_url,
        schema=settings.reports_db_schema,
        connect_timeout_seconds=settings.access_database_timeout_seconds,
    )
    doperacoes_import_service = DOperacoesImportService(
        database_url=settings.reports_database_url,
        schema=settings.reports_db_schema,
        connect_timeout_seconds=settings.access_database_timeout_seconds,
    )
    drevendas_import_service = DRevendasImportService(
        database_url=settings.reports_database_url,
        schema=settings.reports_db_schema,
        connect_timeout_seconds=settings.access_database_timeout_seconds,
    )
    filial_labels = drevendas_import_service.latest_labels() or dict(FILIAL_LABELS)
    set_filial_labels(filial_labels)
    dcondicoes_import_service = DCondicoesImportService(
        database_url=settings.reports_database_url,
        schema=settings.reports_db_schema,
        connect_timeout_seconds=settings.access_database_timeout_seconds,
    )
    dprodutos_import_service = DProdutosImportService(
        database_url=settings.reports_database_url,
        schema=settings.reports_db_schema,
        connect_timeout_seconds=settings.access_database_timeout_seconds,
    )
    produto_cestas_import_service = ProdutoCestasImportService(
        database_url=settings.reports_database_url,
        schema=settings.reports_db_schema,
        connect_timeout_seconds=settings.access_database_timeout_seconds,
    )
    boletos_pdf_import_service = BoletosPdfImportService(
        database_url=settings.reports_database_url,
        schema=settings.reports_db_schema,
        connect_timeout_seconds=settings.access_database_timeout_seconds,
    )
    boletos_pdf_import_services = {
        filial_code: BoletosPdfImportService(
            database_url=settings.reports_database_url,
            schema=settings.reports_db_schema,
            dataset_name=f"boletos_bradesco_op_{filial_code}",
            expected_filial=filial_code,
            connect_timeout_seconds=settings.access_database_timeout_seconds,
        )
        for filial_code in sorted(filial_labels, key=int)
    }
    dclientes_import_service = DClientesImportService(
        database_url=settings.reports_database_url,
        schema=settings.reports_db_schema,
        connect_timeout_seconds=settings.access_database_timeout_seconds,
    )
    clientes_score_import_service = ClientesScoreImportService(
        database_url=settings.reports_database_url,
        schema=settings.reports_db_schema,
        connect_timeout_seconds=settings.access_database_timeout_seconds,
    )
    inadimplencia_import_service = InadimplenciaImportService(
        database_url=settings.reports_database_url,
        schema=settings.reports_db_schema,
        connect_timeout_seconds=settings.access_database_timeout_seconds,
    )
    comodatos_import_service = ComodatosImportService(
        database_url=settings.reports_database_url,
        schema=settings.reports_db_schema,
        connect_timeout_seconds=settings.access_database_timeout_seconds,
    )
    giro_import_service = GiroImportService(
        database_url=settings.reports_database_url,
        schema=settings.reports_db_schema,
        connect_timeout_seconds=settings.access_database_timeout_seconds,
    )
    critica_rn_import_service = CriticaRnImportService(
        database_url=settings.reports_database_url,
        schema=settings.reports_db_schema,
        connect_timeout_seconds=settings.access_database_timeout_seconds,
    )
    critica_operacao_import_services = {
        filial_code: CriticaOperacaoImportService(
            database_url=settings.reports_database_url,
            schema=settings.reports_db_schema,
            dataset_name=f"critica_op_{filial_code}",
            expected_filial=filial_code,
            connect_timeout_seconds=settings.access_database_timeout_seconds,
        )
        for filial_code in sorted(filial_labels, key=int)
    }
    critica_operacao_admin_service = critica_operacao_import_services[sorted(filial_labels, key=int)[0]]
    documentacao_pendente_import_service = DocumentacaoPendenteImportService(
        database_url=settings.reports_database_url,
        schema=settings.reports_db_schema,
        connect_timeout_seconds=settings.access_database_timeout_seconds,
    )
    prazo_limite_import_service = PrazoLimiteImportService(
        database_url=settings.reports_database_url,
        schema=settings.reports_db_schema,
        connect_timeout_seconds=settings.access_database_timeout_seconds,
    )
    recolha_request_service = RecolhaRequestService(
        project_root / "exports" / "recolhas" / "solicitacoes_recolha.csv"
    )
    evolution_client = EvolutionClient(
        EvolutionConfig(
            base_url=settings.evolution_base_url,
            api_key=settings.evolution_api_key,
            instance=settings.evolution_instance,
            send_path=settings.evolution_send_path,
            list_path=settings.evolution_list_path,
            buttons_path=settings.evolution_buttons_path,
            media_path=settings.evolution_media_path,
            timeout_seconds=settings.evolution_timeout_seconds,
        )
    )
    meta_cloud_client = MetaCloudClient(
        MetaCloudConfig(
            enabled=settings.meta_cloud_enabled,
            api_version=settings.meta_cloud_api_version,
            phone_number_id=settings.meta_cloud_phone_number_id,
            access_token=settings.meta_cloud_access_token,
            verify_token=settings.meta_cloud_verify_token,
        )
    )
    access_control = AccessControl(
        enabled=settings.access_control_enabled,
        database_url=settings.access_database_url,
        schema=settings.access_db_schema,
        public_enabled=settings.access_public_enabled,
        connect_timeout_seconds=settings.access_database_timeout_seconds,
    )
    security_monitor = SecurityMonitor(
        enabled=settings.security_audit_enabled,
        database_url=settings.access_database_url,
        schema=settings.access_db_schema,
        connect_timeout_seconds=settings.access_database_timeout_seconds,
        default_cooldown_minutes=settings.denied_reply_cooldown_minutes,
        unregistered_cooldown_minutes=settings.denied_unregistered_reply_cooldown_minutes,
    )
    payip_payments_service = _build_payip_payments_service(settings, logger=logger)
    lookup_flow = CustomerLookupFlow(
        query_service=dclientes_query_service,
        inadimplencia_service=inadimplencia_query_service,
        comodatos_service=comodatos_query_service,
        giro_service=giro_query_service,
        critica_rn_service=critica_rn_query_service,
        documentacao_pendente_service=documentacao_pendente_query_service,
        prazo_limite_service=prazo_limite_query_service,
        boletos_service=boletos_query_service,
        payip_payments_service=payip_payments_service,
        recolha_request_service=recolha_request_service,
        access_control=access_control,
        clientes_score_service=clientes_score_query_service,
    )
    return AppServices(
        admin_import_job_service=admin_import_job_service,
        dclientes_query_service=dclientes_query_service,
        clientes_score_query_service=clientes_score_query_service,
        inadimplencia_query_service=inadimplencia_query_service,
        comodatos_query_service=comodatos_query_service,
        giro_query_service=giro_query_service,
        critica_rn_query_service=critica_rn_query_service,
        critica_rn_pdf_prebuild_service=critica_rn_pdf_prebuild_service,
        documentacao_pendente_query_service=documentacao_pendente_query_service,
        prazo_limite_query_service=prazo_limite_query_service,
        boletos_query_service=boletos_query_service,
        dsetores_import_service=dsetores_import_service,
        dprecos_import_service=dprecos_import_service,
        doperacoes_import_service=doperacoes_import_service,
        drevendas_import_service=drevendas_import_service,
        dcondicoes_import_service=dcondicoes_import_service,
        dprodutos_import_service=dprodutos_import_service,
        produto_cestas_import_service=produto_cestas_import_service,
        boletos_pdf_import_service=boletos_pdf_import_service,
        boletos_pdf_import_services=boletos_pdf_import_services,
        dclientes_import_service=dclientes_import_service,
        clientes_score_import_service=clientes_score_import_service,
        inadimplencia_import_service=inadimplencia_import_service,
        comodatos_import_service=comodatos_import_service,
        giro_import_service=giro_import_service,
        critica_rn_import_service=critica_rn_import_service,
        critica_operacao_import_services=critica_operacao_import_services,
        critica_operacao_admin_service=critica_operacao_admin_service,
        documentacao_pendente_import_service=documentacao_pendente_import_service,
        prazo_limite_import_service=prazo_limite_import_service,
        recolha_request_service=recolha_request_service,
        evolution_client=evolution_client,
        meta_cloud_client=meta_cloud_client,
        access_control=access_control,
        security_monitor=security_monitor,
        payip_payments_service=payip_payments_service,
        lookup_flow=lookup_flow,
        filial_labels=filial_labels,
    )


def _build_payip_payments_service(settings: Any, *, logger: logging.Logger) -> PayipPaymentsService | None:
    if not (
        settings.payip_base_url
        and settings.payip_client_id
        and settings.payip_username
        and settings.payip_password
        and (settings.payip_company_id or settings.payip_company_ids)
    ):
        return None
    try:
        return build_payip_payments_service(settings)
    except RuntimeError as exc:
        logger.warning("PayIP nao inicializada: %s", exc)
        return None
