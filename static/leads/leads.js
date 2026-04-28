/* Utilitários compartilhados do módulo de Leads.
 * Carrega antes de kanban.js / card-modal.js.
 *
 * Equivalente ao CardModalProvider do React: gerencia abertura/fechamento
 * do modal do card, sincroniza ?card=<id> com history.pushState e responde
 * a popstate (botão voltar).
 */

(function () {
  // ---------- SLA / prazo da etapa ----------

  function computeStageDeadline(stageEnteredAt, slaDays) {
    if (!slaDays || !stageEnteredAt) return null;
    const due = new Date(stageEnteredAt).getTime() + Number(slaDays) * 86400000;
    const remaining = Math.ceil((due - Date.now()) / 86400000);
    const label = new Date(due).toLocaleDateString('pt-BR');
    if (remaining < 0)  return { text: `${Math.abs(remaining)}d atraso (${label})`, color: 'text-danger fw-medium' };
    if (remaining === 0) return { text: `Vence hoje (${label})`,                   color: 'text-warning fw-medium' };
    if (remaining <= 1)  return { text: `${remaining}d (${label})`,                color: 'text-warning fw-medium' };
    return { text: `${remaining}d (${label})`, color: 'text-secondary' };
  }

  function daysUntil(dateStr) {
    if (!dateStr) return null;
    const due = new Date(dateStr + 'T00:00:00').getTime();
    return Math.ceil((due - Date.now()) / 86400000);
  }

  function applyDeadlines(root) {
    (root || document).querySelectorAll('.lead-deadline').forEach(el => {
      const info = computeStageDeadline(el.dataset.entered, el.dataset.sla);
      if (!info) { el.textContent = '—'; return; }
      el.textContent = info.text;
      el.className = `lead-deadline small ${info.color}`;
      // Color kanban card border based on SLA status
      const card = el.closest('.kanban-card');
      if (card) {
        card.classList.remove('kanban-card-overdue', 'kanban-card-due-today');
        if (info.color.includes('text-danger')) card.classList.add('kanban-card-overdue');
        else if (info.color.includes('text-warning')) card.classList.add('kanban-card-due-today');
      }
    });

    // Deadline badges on kanban cards — CNPJ and NF
    function applyCardDeadlineBadge(el, spanSelector, markCard) {
      const d = daysUntil(el.dataset.due);
      const span = el.querySelector(spanSelector);
      if (!span) return;
      if (d === null) { el.style.display='none'; return; }
      const card = el.closest('.kanban-card');
      if (d < 0) {
        span.textContent = `${Math.abs(d)}d atraso`;
        el.style.background = '#fef2f2'; el.style.color = '#b91c1c';
        if (card && markCard) card.classList.add('kanban-card-overdue');
      } else if (d === 0) {
        span.textContent = 'vence hoje';
        el.style.background = '#fff7ed'; el.style.color = '#c2410c';
        if (card && markCard) card.classList.add('kanban-card-due-today');
      } else if (d <= 3) {
        span.textContent = `${d}d`;
        el.style.background = '#fff7ed'; el.style.color = '#c2410c';
      } else {
        span.textContent = `${d}d`;
      }
    }
    (root || document).querySelectorAll('.lead-deadline-cnpj').forEach(el => applyCardDeadlineBadge(el, '.cnpj-days', true));
    (root || document).querySelectorAll('.lead-deadline-nf').forEach(el => applyCardDeadlineBadge(el, '.nf-days', false));

    // Deadline badges on card modal header — show days remaining and colorize
    (root || document).querySelectorAll('.deadline-badge-junta,.deadline-badge-nf,.deadline-badge-total').forEach(el => {
      const d = daysUntil(el.dataset.due);
      const txt = el.querySelector('.badge-days-text');
      if (d === null) return;
      if (d < 0) {
        el.style.background = '#fef2f2'; el.style.color = '#b91c1c';
        if (txt) txt.textContent = `${Math.abs(d)}d atraso`;
      } else if (d === 0) {
        el.style.background = '#fff7ed'; el.style.color = '#c2410c';
        if (txt) txt.textContent = 'vence hoje';
      } else if (d <= 3) {
        el.style.background = '#fff7ed'; el.style.color = '#c2410c';
        if (txt) txt.textContent = `${d}d`;
      } else {
        if (txt) txt.textContent = `${d}d`;
      }
    });

    // Convert UTC timestamps to local time
    (root || document).querySelectorAll('.ts-local[data-ts]').forEach(el => {
      try {
        const ts = el.dataset.ts;
        if (!ts) return;
        const d = new Date(ts.endsWith('Z') ? ts : ts + 'Z');
        if (isNaN(d)) return;
        const dd = String(d.getDate()).padStart(2,'0');
        const mm = String(d.getMonth()+1).padStart(2,'0');
        const hh = String(d.getHours()).padStart(2,'0');
        const mi = String(d.getMinutes()).padStart(2,'0');
        el.textContent = `${dd}/${mm} ${hh}:${mi}`;
      } catch(e) {}
    });
  }

  // ---------- Card modal (provider equivalente) ----------

  let openedId = null;
  let backdropEl = null;

  function ensureBackdrop() {
    backdropEl = document.getElementById('cardModalBackdrop');
    return backdropEl;
  }

  async function openCard(leadId, opts = {}) {
    if (!ensureBackdrop()) return;
    if (openedId === leadId) return;
    openedId = leadId;
    if (!opts.skipHistory) {
      const url = new URL(location.href);
      url.searchParams.set('card', leadId);
      history.pushState({ card: leadId }, '', url.toString());
    }
    backdropEl.hidden = false;
    // força reflow antes de aplicar a classe pra animação rodar
    void backdropEl.offsetHeight;
    backdropEl.classList.add('visible');

    const body = document.getElementById('cardModalBody');
    body.innerHTML = '<div class="text-center text-muted py-5"><div class="spinner-border"></div></div>';
    try {
      const html = await fetch(`/api/leads/${leadId}/modal`).then(r => r.text());
      body.innerHTML = html;
      // bind handlers
      window.LeadModal._bindModalHandlers(body, leadId);
      applyDeadlines(body);
    } catch (e) {
      body.innerHTML = `<div class="alert alert-danger m-3">Erro ao carregar: ${e.message}</div>`;
    }
  }

  function closeCard(opts = {}) {
    if (!ensureBackdrop()) return;
    openedId = null;
    backdropEl.classList.remove('visible');
    setTimeout(() => { backdropEl.hidden = true; }, 250);
    if (!opts.skipHistory) {
      const url = new URL(location.href);
      url.searchParams.delete('card');
      history.pushState({}, '', url.toString());
    }
  }

  // Click fora / botão fechar / ESC
  function bindGlobal() {
    if (!ensureBackdrop()) return;
    backdropEl.addEventListener('click', (e) => {
      if (e.target === backdropEl) closeCard();
      if (e.target.closest('.card-modal-close')) closeCard();
    });
    document.addEventListener('keydown', (e) => {
      if (e.key === 'Escape' && !backdropEl.hidden) closeCard();
    });

    // Linhas da lista / cards do kanban
    document.addEventListener('click', (e) => {
      const row = e.target.closest('.lead-row, .kanban-card');
      if (!row || !row.dataset.leadId) return;
      // ignora cliques dentro do drag handle do kanban (deixa SortableJS lidar)
      if (e.target.closest('.kanban-grip')) return;
      e.preventDefault();
      openCard(row.dataset.leadId);
    });

    // popstate (botão voltar)
    window.addEventListener('popstate', () => {
      const id = new URL(location.href).searchParams.get('card');
      if (id) openCard(id, { skipHistory: true });
      else if (openedId) closeCard({ skipHistory: true });
    });

    // se entrou na página com ?card= já aberto
    const initial = new URL(location.href).searchParams.get('card');
    if (initial) openCard(initial, { skipHistory: true });
  }

  document.addEventListener('DOMContentLoaded', () => {
    applyDeadlines();
    bindGlobal();
  });

  async function reloadCard(leadId) {
    if (!ensureBackdrop()) return;
    openedId = null;  // reset so openCard doesn't short-circuit
    await openCard(leadId, { skipHistory: true });
  }

  // expõe API para outros scripts
  window.LeadModal = {
    open: openCard,
    close: closeCard,
    applyDeadlines,
    _reload: reloadCard,
    _bindModalHandlers: () => {},  // sobrescrito por card-modal.js
  };
})();
