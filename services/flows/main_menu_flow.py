from __future__ import annotations

from typing import Any


def _customer_flow_module() -> Any:
    from bot_api.services import customer_lookup_flow

    return customer_lookup_flow


class MainMenuFlow:
    def __init__(self, context: Any) -> None:
        self.context = context

    def __getattr__(self, name: str) -> Any:
        return getattr(self.context, name)

    def _main_menu_summary_option_id(self, decision: AccessDecision) -> str:
        flow = _customer_flow_module()
        if not self._can_use_gv_summary_menu(decision):
            return ''
        if self._is_gerente_vendas(decision):
            return flow.MENU_MANAGER
        return flow.MENU_GV_SUMMARY

    def _main_menu_option_ids(self, decision: AccessDecision) -> list[str]:
        flow = _customer_flow_module()
        option_ids: list[str] = []
        can_use_cliente = self._has_area_access(decision, 'cliente')
        can_use_inadimplencia = self._has_area_access(decision, 'inadimplencia')
        can_use_comodato = self._has_area_access(decision, 'comodato')
        can_use_estoque = self._has_area_access(decision, 'estoque')
        can_use_documentacao = can_use_cliente
        if self._is_armazem(decision):
            can_use_inadimplencia = False
            can_use_comodato = False
            can_use_documentacao = False
        can_use_visit_menu = self._can_use_visit_menu(decision) and can_use_cliente
        can_use_finance_menu = self._can_use_finance_menu(decision) and can_use_inadimplencia
        can_use_seller_summary_menu = self._can_use_seller_summary_menu(decision) and can_use_inadimplencia
        can_use_seller_risk_menu = self._can_use_seller_risk_menu(decision) and can_use_inadimplencia
        summary_option_id = self._main_menu_summary_option_id(decision)
        if self._is_vendedor(decision):
            if can_use_visit_menu:
                option_ids.append(flow.MENU_VISIT_DAY)
            if can_use_seller_risk_menu:
                option_ids.append(flow.MENU_SELLER_RISK)
            if can_use_cliente and not self._is_armazem(decision):
                option_ids.append(flow.MENU_GIRO)
            if can_use_documentacao:
                option_ids.append(flow.MENU_DOCUMENTACAO)
            if can_use_cliente:
                option_ids.append(flow.MENU_SEARCH)
            if can_use_inadimplencia:
                option_ids.append(flow.MENU_INADIMPLENCIA)
            if can_use_comodato:
                option_ids.append(flow.MENU_COMODATOS)
            if can_use_cliente:
                option_ids.append(flow.MENU_SELLER_FINANCEIRO)
            if can_use_seller_summary_menu:
                option_ids.append(flow.MENU_SELLER_SUMMARY)
            if can_use_cliente:
                option_ids.append(flow.MENU_CRITICA)
        elif self._is_gerente_vendas(decision):
            if summary_option_id:
                option_ids.append(summary_option_id)
            if can_use_visit_menu:
                option_ids.append(flow.MENU_VISIT_DAY)
            if can_use_inadimplencia:
                option_ids.append(flow.MENU_INADIMPLENCIA)
            if can_use_cliente and not self._is_armazem(decision):
                option_ids.append(flow.MENU_GIRO)
            if can_use_documentacao:
                option_ids.append(flow.MENU_DOCUMENTACAO)
            if can_use_cliente:
                option_ids.append(flow.MENU_SEARCH)
            if can_use_comodato:
                option_ids.append(flow.MENU_COMODATOS)
            if can_use_cliente:
                option_ids.append(flow.MENU_SELLER_FINANCEIRO)
            if can_use_cliente:
                option_ids.append(flow.MENU_CRITICA)
        elif self._is_diretor_comercial(decision):
            if summary_option_id:
                option_ids.append(summary_option_id)
            if can_use_visit_menu:
                option_ids.append(flow.MENU_VISIT_DAY)
            if can_use_inadimplencia:
                option_ids.append(flow.MENU_INADIMPLENCIA)
            if can_use_cliente:
                option_ids.append(flow.MENU_GIRO)
            if can_use_documentacao:
                option_ids.append(flow.MENU_DOCUMENTACAO)
            if can_use_cliente:
                option_ids.append(flow.MENU_SEARCH)
            if can_use_comodato:
                option_ids.append(flow.MENU_COMODATOS)
            if can_use_estoque:
                option_ids.append(flow.MENU_ARMAZEM)
        else:
            if can_use_cliente:
                option_ids.append(flow.MENU_SEARCH)
            if self._is_armazem(decision):
                option_ids.append(flow.MENU_ARMAZEM)
            if can_use_inadimplencia:
                option_ids.append(flow.MENU_INADIMPLENCIA)
            if can_use_cliente:
                option_ids.append(flow.MENU_GIRO)
            if can_use_documentacao:
                option_ids.append(flow.MENU_DOCUMENTACAO)
            if can_use_visit_menu:
                option_ids.append(flow.MENU_VISIT_DAY)
            if can_use_comodato:
                option_ids.append(flow.MENU_COMODATOS)
            if summary_option_id:
                option_ids.append(summary_option_id)
            if can_use_seller_summary_menu:
                option_ids.append(flow.MENU_SELLER_SUMMARY)
                if can_use_seller_risk_menu:
                    option_ids.append(flow.MENU_SELLER_RISK)
            if can_use_finance_menu:
                option_ids.append(flow.MENU_FINANCEIRO)
        if self._is_admin(decision):
            option_ids.append(flow.MENU_ADMIN_ACCESS)
        return option_ids

    def _main_menu_shortcuts(self, decision: AccessDecision) -> dict[str, str]:
        flow = _customer_flow_module()
        option_ids = self._main_menu_option_ids(decision)
        return {option_id: str(index) for index, option_id in enumerate(option_ids, start=1)}

    def _build_main_menu(self, decision: AccessDecision, invalid_selection: bool=False) -> OutgoingMessage:
        flow = _customer_flow_module()
        can_use_cliente = self._has_area_access(decision, 'cliente')
        can_use_inadimplencia = self._has_area_access(decision, 'inadimplencia')
        can_use_comodato = self._has_area_access(decision, 'comodato')
        can_use_estoque = self._has_area_access(decision, 'estoque')
        if self._is_armazem(decision):
            can_use_inadimplencia = False
            can_use_comodato = False
        can_use_giro = can_use_cliente and not self._is_armazem(decision)
        can_use_documentacao = can_use_cliente and not self._is_armazem(decision)
        can_use_visit_menu = self._can_use_visit_menu(decision) and can_use_cliente
        can_use_finance_menu = self._can_use_finance_menu(decision) and can_use_inadimplencia
        can_use_gv_summary_menu = self._can_use_gv_summary_menu(decision) and can_use_inadimplencia
        can_use_seller_summary_menu = self._can_use_seller_summary_menu(decision) and can_use_inadimplencia
        can_use_seller_risk_menu = self._can_use_seller_risk_menu(decision) and can_use_inadimplencia
        shortcut_map = self._main_menu_shortcuts(decision)
        option_ids = self._main_menu_option_ids(decision)
        summary_option_id = self._main_menu_summary_option_id(decision)
        option_specs: dict[str, flow.InteractiveOption] = {}
        if can_use_cliente:
            option_specs[flow.MENU_SEARCH] = flow.InteractiveOption(option_id=flow.MENU_SEARCH, title='Buscar Cliente', description='Encontrar um cliente da sua base', shortcut=shortcut_map.get(flow.MENU_SEARCH, ''))
        if can_use_inadimplencia:
            inad_title = 'Titulos em Aberto'
            inad_description = 'Ver vencidos e proximos vencimentos'
            if self._is_vendedor(decision):
                inad_title = 'Cobranca da Carteira'
                inad_description = 'Ver inadimplentes e proximos vencimentos da sua base'
            elif self._is_gerente_vendas(decision):
                inad_title = 'Cobranca da Gerencia'
                inad_description = 'Ver inadimplentes e proximos vencimentos do GV'
            elif self._is_diretor_comercial(decision):
                inad_title = 'Cobranca'
                inad_description = 'Ver inadimplentes e proximos vencimentos'
            option_specs[flow.MENU_INADIMPLENCIA] = flow.InteractiveOption(option_id=flow.MENU_INADIMPLENCIA, title=inad_title, description=inad_description, shortcut=shortcut_map.get(flow.MENU_INADIMPLENCIA, ''))
        if can_use_giro:
            giro_title = 'Risco de Giro'
            giro_description = 'Ver oportunidades de caixa por dia'
            if self._is_vendedor(decision):
                giro_title = 'Giro'
                giro_description = 'Ver oportunidades de caixa por dia'
            elif self._is_gerente_vendas(decision):
                giro_title = 'Giro da Gerencia'
                giro_description = 'Ver oportunidades de caixa por dia no GV'
            elif self._is_diretor_comercial(decision):
                giro_title = 'Giro'
                giro_description = 'Ver oportunidades de caixa por dia'
            option_specs[flow.MENU_GIRO] = flow.InteractiveOption(option_id=flow.MENU_GIRO, title=giro_title, description=giro_description, shortcut=shortcut_map.get(flow.MENU_GIRO, ''))
        if can_use_documentacao:
            option_specs[flow.MENU_DOCUMENTACAO] = flow.InteractiveOption(option_id=flow.MENU_DOCUMENTACAO, title='Documentacao Pendente', description='Ver documentos faltando por cliente e por dia', shortcut=shortcut_map.get(flow.MENU_DOCUMENTACAO, ''))
        if (self._is_vendedor(decision) or self._is_gerente_vendas(decision)) and can_use_cliente:
            option_specs[flow.MENU_SELLER_FINANCEIRO] = flow.InteractiveOption(option_id=flow.MENU_SELLER_FINANCEIRO, title='Financeiro', description='Solicitar recolha ou boleto', shortcut=shortcut_map.get(flow.MENU_SELLER_FINANCEIRO, ''))
        footer = 'Responda com o numero ou com o nome da opcao.'
        if can_use_visit_menu:
            visit_title = 'Rota do Dia'
            visit_description = 'Ver os clientes da rota de hoje'
            if self._is_gerente_vendas(decision):
                visit_description = 'Ver a rota do dia por setor'
            elif self._is_diretor_comercial(decision):
                visit_description = 'Ver a rota do dia por GV e setor'
            option_specs[flow.MENU_VISIT_DAY] = flow.InteractiveOption(option_id=flow.MENU_VISIT_DAY, title=visit_title, description=visit_description, shortcut=shortcut_map.get(flow.MENU_VISIT_DAY, ''))
        if can_use_comodato:
            option_specs[flow.MENU_COMODATOS] = flow.InteractiveOption(option_id=flow.MENU_COMODATOS, title='Comodatos', description='Ver pendencias de comodato', shortcut=shortcut_map.get(flow.MENU_COMODATOS, ''))
        if can_use_gv_summary_menu:
            summary_title = 'Resumo da Gerencia'
            summary_description = 'Ver um resumo rapido do seu GV'
            summary_footer = 'Responda com o numero ou com o nome da opcao.'
            if self._is_diretor_comercial(decision):
                summary_title = 'Diretoria'
                summary_description = 'Risco, cobranca, GVs, filiais e giro'
                summary_footer = 'Responda com o numero ou com o nome da opcao. Use esse menu como rotina da diretoria: diretoria, rota, cobranca, giro, cliente e comodatos.'
            elif self._is_gerente_vendas(decision):
                summary_title = 'Gerencia'
                summary_description = 'Painel consolidado da gerencia: risco, vencimentos, equipe, filiais e resumo'
                summary_footer = 'Responda com o numero ou com o nome da opcao. Atalhos uteis: gerencia, rota segunda, inad segunda, giro segunda, vencimentos e equipe.'
            option_specs[summary_option_id] = flow.InteractiveOption(option_id=summary_option_id, title=summary_title, description=summary_description, shortcut=shortcut_map.get(summary_option_id, ''))
            footer = summary_footer
        if can_use_seller_summary_menu:
            option_specs[flow.MENU_SELLER_SUMMARY] = flow.InteractiveOption(option_id=flow.MENU_SELLER_SUMMARY, title='Carteira', description='Ver base, rota, risco e giro da sua carteira', shortcut=shortcut_map.get(flow.MENU_SELLER_SUMMARY, ''))
            if can_use_seller_risk_menu:
                option_specs[flow.MENU_SELLER_RISK] = flow.InteractiveOption(option_id=flow.MENU_SELLER_RISK, title='Risco da Rota', description='Ver clientes da rota com atraso ou vencimento', shortcut=shortcut_map.get(flow.MENU_SELLER_RISK, ''))
            footer = 'Responda com o numero ou com o nome da opcao. Atalhos uteis: rota segunda, giro quinta, inad hoje, 3 6643 e inad santa maria.'
        if (self._is_vendedor(decision) or self._is_gerente_vendas(decision)) and can_use_cliente:
            option_specs[flow.MENU_CRITICA] = flow.InteractiveOption(option_id=flow.MENU_CRITICA, title='Critica', description='Resumo e PDFs da critica RN', shortcut=shortcut_map.get(flow.MENU_CRITICA, ''))
        if can_use_finance_menu:
            option_specs[flow.MENU_FINANCEIRO] = flow.InteractiveOption(option_id=flow.MENU_FINANCEIRO, title='Financeiro', description='Ver resumo e cobrancas', shortcut=shortcut_map.get(flow.MENU_FINANCEIRO, ''))
            footer = 'Responda com o numero ou com o nome da opcao.'
        show_armazem_menu = self._is_armazem(decision) or (self._is_diretor_comercial(decision) and can_use_estoque)
        if show_armazem_menu:
            option_specs[flow.MENU_ARMAZEM] = flow.InteractiveOption(option_id=flow.MENU_ARMAZEM, title='Armazem', description='Consultar estoque por produto', shortcut=shortcut_map.get(flow.MENU_ARMAZEM, ''))
        if self._is_armazem(decision):
            footer = 'Responda com o numero ou com o nome da opcao. Atalhos: estoque 3 13203 ou armazem 3 13203.'
        if self._is_admin(decision):
            option_specs[flow.MENU_ADMIN_ACCESS] = flow.InteractiveOption(option_id=flow.MENU_ADMIN_ACCESS, title='Admin', description='Cadastrar ou ajustar acessos', shortcut=shortcut_map.get(flow.MENU_ADMIN_ACCESS, ''))
            if self._can_use_finance_menu(decision):
                footer = 'Responda com o numero ou com o nome da opcao.'
            else:
                footer = 'Responda com o numero ou com o nome da opcao.'
        options = [option_specs[option_id] for option_id in option_ids if option_id in option_specs]
        text = 'Escolha o que voce quer acompanhar agora.'
        if invalid_selection:
            text = flow._invalid_option_text('Escolha uma opcao do menu.')
        if not options:
            if not decision.allowed:
                text = 'Seu numero ainda nao esta cadastrado para usar o bot.\nPeca a liberacao ao responsavel e tente novamente.'
            else:
                text = 'Seu numero esta ativo, mas ainda nao encontrei menus liberados para ele.\nPeca a liberacao ao responsavel e tente novamente.'
        return flow.OutgoingMessage(kind='menu', title='Consultas', text=text, footer=footer, button_text='Ver opcoes', options=tuple(options))
