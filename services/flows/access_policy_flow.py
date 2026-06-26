from __future__ import annotations

from typing import Any


def _customer_flow_module() -> Any:
    from bot_api.services import customer_lookup_flow

    return customer_lookup_flow


class AccessPolicyFlow:
    def __init__(self, context: Any) -> None:
        self.context = context

    def __getattr__(self, name: str) -> Any:
        return getattr(self.context, name)

    def _is_admin(self, decision: AccessDecision) -> bool:
        flow = _customer_flow_module()
        return flow.ROLE_ADMIN in decision.roles

    def _is_financeiro(self, decision: AccessDecision) -> bool:
        flow = _customer_flow_module()
        if self._is_admin(decision):
            return False
        return flow.ROLE_FINANCEIRO in decision.roles

    def _is_vendedor(self, decision: AccessDecision) -> bool:
        flow = _customer_flow_module()
        if self._is_admin(decision):
            return False
        return flow.ROLE_VENDEDOR in decision.roles

    def _is_gerente_vendas(self, decision: AccessDecision) -> bool:
        flow = _customer_flow_module()
        if self._is_admin(decision):
            return False
        return flow.ROLE_GERENTE_VENDAS in decision.roles

    def _is_diretor_comercial(self, decision: AccessDecision) -> bool:
        flow = _customer_flow_module()
        if self._is_admin(decision):
            return False
        return flow.ROLE_DIRETOR_COMERCIAL in decision.roles

    def _can_use_finance_menu(self, decision: AccessDecision) -> bool:
        flow = _customer_flow_module()
        return self._is_admin(decision) or self._is_financeiro(decision)

    def _can_use_critica(self, decision: AccessDecision) -> bool:
        flow = _customer_flow_module()
        return self._is_vendedor(decision) or self._is_gerente_vendas(decision)

    def _can_use_payip_menu(self, decision: AccessDecision) -> bool:
        flow = _customer_flow_module()
        return self._can_use_finance_menu(decision) and self._has_area_access(decision, 'payip')

    def _has_unrestricted_lookup_access(self, decision: AccessDecision) -> bool:
        flow = _customer_flow_module()
        if self._is_admin(decision):
            return True
        return self._is_financeiro(decision) and (not decision.sectors) and (not decision.gv_vdes)

    def _can_access_sectors(self, decision: AccessDecision) -> bool:
        flow = _customer_flow_module()
        if self._has_unrestricted_lookup_access(decision):
            return True
        return bool(decision.sectors or decision.gv_vdes)

    def _allowed_sectors(self, decision: AccessDecision) -> list[str] | None:
        flow = _customer_flow_module()
        if self._has_unrestricted_lookup_access(decision):
            return None
        return list(decision.sectors)

    def _allowed_gv_vdes(self, decision: AccessDecision) -> list[str] | None:
        flow = _customer_flow_module()
        if self._has_unrestricted_lookup_access(decision):
            return None
        return list(decision.gv_vdes)

    def _can_use_visit_menu(self, decision: AccessDecision) -> bool:
        flow = _customer_flow_module()
        if self._is_admin(decision):
            return False
        return self._uses_grouped_visit_flow(decision) or self._is_vendedor(decision)

    def _can_use_gv_summary_menu(self, decision: AccessDecision) -> bool:
        flow = _customer_flow_module()
        return (self._is_gerente_vendas(decision) or self._is_diretor_comercial(decision)) and self._can_access_sectors(decision)

    def _can_use_seller_summary_menu(self, decision: AccessDecision) -> bool:
        flow = _customer_flow_module()
        return self._is_vendedor(decision) and self._can_access_sectors(decision)

    def _can_use_seller_risk_menu(self, decision: AccessDecision) -> bool:
        flow = _customer_flow_module()
        return self._is_vendedor(decision) and self._can_access_sectors(decision)

    def _decision_for_area(self, decision: AccessDecision, area: str) -> AccessDecision:
        flow = _customer_flow_module()
        normalized_area = flow._normalize_choice(area) or 'cliente'
        if not decision.normalized_number or not self.access_control.enabled:
            return decision
        if decision.area == normalized_area and decision.allowed:
            return decision
        return self.access_control.authorize(phone_number=decision.normalized_number, area=normalized_area)

    def _has_area_access(self, decision: AccessDecision, area: str) -> bool:
        flow = _customer_flow_module()
        return self._decision_for_area(decision, area).allowed

    def _build_area_access_denied_response(self, area: str) -> OutgoingMessage:
        flow = _customer_flow_module()
        if area == 'inadimplencia':
            return flow.OutgoingMessage(text='Seu numero ainda nao tem acesso a essa consulta de inadimplencia.\nPeca a liberacao ao responsavel e tente novamente.')
        if area == 'comodato':
            return flow.OutgoingMessage(text='Seu numero ainda nao tem acesso a essa consulta de comodatos.\nPeca a liberacao ao responsavel e tente novamente.')
        return flow.OutgoingMessage(text='Seu numero ainda nao tem acesso a essa consulta.\nPeca a liberacao ao responsavel e tente novamente.')

    def _ensure_scoped_lookup_access(self, decision: AccessDecision, search_context: str) -> OutgoingMessage | None:
        flow = _customer_flow_module()
        status_error = self._ensure_search_context_ready(search_context, decision=decision)
        if status_error is not None:
            return status_error
        if not self._can_access_sectors(decision):
            if search_context == 'inadimplencia':
                return flow.OutgoingMessage(text='Seu numero ainda nao esta liberado com um escopo comercial para consultar a inadimplencia.\nPeca esse ajuste ao responsavel e tente novamente.')
            if search_context == 'comodato':
                return flow.OutgoingMessage(text='Seu numero ainda nao esta liberado com um escopo comercial para consultar os comodatos.\nPeca esse ajuste ao responsavel e tente novamente.')
            if search_context == 'giro':
                return flow.OutgoingMessage(text='Seu numero ainda nao esta liberado com um escopo comercial para consultar o giro.\nPeca esse ajuste ao responsavel e tente novamente.')
            if search_context == 'documentacao':
                return flow.OutgoingMessage(text='Seu numero ainda nao esta liberado com um escopo comercial para consultar a documentacao pendente.\nPeca esse ajuste ao responsavel e tente novamente.')
            if search_context == 'prazo_limite':
                return flow.OutgoingMessage(text='Seu numero ainda nao esta liberado para consultar prazo e limite.\nPeca esse ajuste ao responsavel e tente novamente.')
            return flow.OutgoingMessage(text='Seu numero ainda nao esta liberado com um escopo comercial para esse tipo de consulta.\nPara buscar por filial, codigo, nome ou visitas do dia, peca esse ajuste ao responsavel.\nSe preferir, voce pode consultar por CPF ou CNPJ.')
        return None
