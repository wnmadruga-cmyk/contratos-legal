/* Kanban — drag-and-drop com SortableJS + update otimista.
 * Em caso de erro, snapshot é restaurado.
 */

(function () {
  const cols = document.querySelectorAll('.kanban-col-body');
  if (!cols.length || typeof Sortable === 'undefined') return;

  cols.forEach(col => {
    Sortable.create(col, {
      group: 'kanban',
      animation: 160,
      ghostClass: 'sortable-ghost',
      dragClass: 'sortable-drag',
      delay: 60,
      delayOnTouchOnly: true,

      onStart: (e) => {
        // snapshot pra revert
        e.item._snapshot = {
          parent: e.from,
          next:   e.item.nextElementSibling,
        };
      },

      onAdd: async (e) => {
        const stageId      = e.to.dataset.stageId;
        const fromStageName = e.from.dataset.stageName || '';
        // leadId may be on the wrapper div OR on the inner .kanban-card
        const leadId  = e.item.dataset.leadId
                     || (e.item.querySelector('.kanban-card') || {}).dataset?.leadId;
        if (!leadId) {
          const snap = e.item._snapshot;
          if (snap) snap.parent.insertBefore(e.item, snap.next);
          updateCounts();
          return;
        }
        try {
          const res = await fetch(`/api/leads/${leadId}/move`, {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({ stage_id: stageId }),
          });
          if (!res.ok) {
            const body = await res.json().catch(() => ({}));
            if (res.status === 409 && body.require === 'checklist') {
              _showDragError(body.message || 'Conclua os itens obrigatórios do checklist antes de avançar.');
            } else if (res.status === 409 && body.require === 'protocol_data') {
              _showDragError(body.message || 'Preencha os dados do protocolo antes de avançar.');
            } else {
              _showDragError((body.message || body.error) || `Erro HTTP ${res.status}`);
            }
            throw new Error(body.message || `HTTP ${res.status}`);
          }
          const data = await res.json();
          // atualiza o data-entered do prazo no card
          const dl = e.item.querySelector('.lead-deadline');
          if (dl && data.stage_entered_at) {
            dl.dataset.entered = data.stage_entered_at;
            window.LeadModal && window.LeadModal.applyDeadlines(e.item);
          }
          updateCounts();
          // Trigger junta organ modal when dragging OUT of "Protocolo na Junta Comercial"
          if (data.show_junta_modal && window.CardModal && window.CardModal.showJuntaOrganModal) {
            window.CardModal.showJuntaOrganModal(leadId);
          }
        } catch (err) {
          // revert otimista
          const snap = e.item._snapshot;
          if (snap) snap.parent.insertBefore(e.item, snap.next);
          updateCounts();
        }
      },
    });
  });

  function _showDragError(msg) {
    const t = document.createElement('div');
    t.className = 'alert alert-danger position-fixed shadow';
    t.style.cssText = 'bottom:24px;right:24px;z-index:9999;max-width:380px;font-size:13px;';
    t.innerHTML = `<i class="bi bi-exclamation-triangle me-2"></i>${msg}`;
    document.body.appendChild(t);
    setTimeout(() => t.remove(), 4000);
  }

  function updateCounts() {
    document.querySelectorAll('.kanban-col').forEach(col => {
      const body  = col.querySelector('.kanban-col-body');
      const badge = col.querySelector('.kanban-col-count');
      if (body && badge) {
        // Count only visible (non-closed) cards
        const total = body.querySelectorAll('.kanban-card').length;
        const hidden = body.querySelectorAll('.kanban-card-closed').length;
        badge.textContent = total - hidden;
      }
    });
  }
})();
