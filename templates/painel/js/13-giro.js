    function startGiroRouteResize(event, routeId) {
      const tableWrap = findGiroRecolhaRouteTable(routeId);
      if (!tableWrap) return;
      event.preventDefault();
      const startY = Number(event.clientY || 0);
      const startHeight = tableWrap.getBoundingClientRect().height || clampGiroRecolhaRouteHeight(state.giroRecolhaRouteHeights[routeId]);
      document.body.classList.add("is-resizing-route");
      const onMove = moveEvent => {
        const delta = Number(moveEvent.clientY || 0) - startY;
        setGiroRecolhaRouteTableHeight(routeId, startHeight + delta);
      };
      const onUp = () => {
        document.body.classList.remove("is-resizing-route");
        window.removeEventListener("pointermove", onMove);
        window.removeEventListener("pointerup", onUp);
      };
      window.addEventListener("pointermove", onMove);
      window.addEventListener("pointerup", onUp);
    }

    function giroStatusBadges(record) {
      const items = [
        ["Litrinho", record.giro_litrinho, record.gap_litrinho],
        ["Inteira", record.giro_inteira, record.gap_inteira],
        ["Litrao", record.giro_litrao, record.gap_litrao]
      ];
      return items.map(([label, status, gap]) => {
        const normalized = String(status || "-").toUpperCase();
        const cls = normalized === "OK" ? "text-bg-success" : normalized === "ZERO" ? "text-bg-danger" : normalized === "NOK" ? "text-bg-warning" : "text-bg-secondary";
        return `<span class="badge ${cls} me-1 mb-1">${escapeHtml(label)} ${escapeHtml(normalized)} | Faltam ${escapeHtml(gap || "0")}</span>`;
      }).join("");
    }

    function giroBoxWhole(value) {
      return String(Math.trunc(parseGiroRecolhaNumber(value || "0")));
    }

    function giroMissingTypeParts(item) {
      const items = [
        ["Litrinho", item && item.giro_litrinho, item && item.gap_litrinho],
        ["Inteira", item && item.giro_inteira, item && item.gap_inteira],
        ["Litrao", item && item.giro_litrao, item && item.gap_litrao]
      ];
      return items
        .map(([label, status, gap]) => {
          const normalized = String(status || "-").toUpperCase();
          const gapValue = parseGiroRecolhaNumber(gap || "0");
          if (gapValue <= 0 && normalized !== "ZERO" && normalized !== "NOK") return "";
          return `${label} ${giroBoxWhole(gap)} cx (${normalized})`;
        })
        .filter(Boolean);
    }

    function giroMissingTypesText(item) {
      const parts = giroMissingTypeParts(item);
      return parts.length ? parts.join(" | ") : "Sem tipo em falta";
    }

    function giroRouteMissingTypesText(items) {
      const totals = [
        ["Litrinho", "gap_litrinho"],
        ["Inteira", "gap_inteira"],
        ["Litrao", "gap_litrao"]
      ].map(([label, key]) => {
        const total = (items || []).reduce((sum, item) => sum + parseGiroRecolhaNumber(item && item[key]), 0);
        return total > 0 ? `${label} ${Math.trunc(total)} cx` : "";
      }).filter(Boolean);
      return totals.length ? totals.join(" | ") : "Sem tipo em falta";
    }

    function routeGroupLabel(values, emptyLabel = "-") {
      const cleanValues = [...new Set((values || []).map(value => String(value || "").trim()).filter(Boolean))].sort();
      if (cleanValues.length === 1) return cleanValues[0];
      return cleanValues.length ? "Varios" : emptyLabel;
    }

    function disconnectGiroRouteResizeObserver() {
      if (giroRouteResizeObserver) {
        giroRouteResizeObserver.disconnect();
        giroRouteResizeObserver = null;
      }
    }
