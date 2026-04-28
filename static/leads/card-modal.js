/* Handlers internos do card modal — bindados após o HTML ser injetado. */

(function () {
  function debounce(fn, wait) {
    let t;
    return (...args) => { clearTimeout(t); t = setTimeout(() => fn(...args), wait); };
  }

  function patchLead(leadId, payload) {
    return fetch(`/api/leads/${leadId}`, {
      method: 'PATCH',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
    }).then(r => r.json());
  }

  // Stage name constants (must match DB)
  const GUARDED_STAGES = {
    "Em Aprovação com Cliente": "client_approval",
    "Conferência Interna": "internal_review",
    "Assinatura do Cliente e Pagamento": "signature",
    "Protocolo na Junta Comercial": "junta",
  };
  const PASSWORD_STAGES = new Set(["Assinatura do Cliente e Pagamento", "Em Aprovação com Cliente"]);

  function bindModal(root, leadId) {
    // ---- Autosave de campos simples (lead-field) ----
    // Status change: intercept statuses that require comment
    const CLOSED_STATUSES     = new Set(['Cancelado', 'Inativo Pedido Cliente']);
    const COMMENT_REQ_STATUSES = new Set(['Cancelado', 'Inativo Pedido Cliente',
                                          'Aguardando Cliente', 'Aguardando Órgão Público']);
    const debouncedSave = debounce((field, value) => {
      patchLead(leadId, { [field]: value });
    }, 600);
    root.querySelectorAll('.lead-field').forEach(el => {
      const evt = (el.tagName === 'SELECT') ? 'change' : 'input';
      if (el.tagName === 'SELECT' && el.dataset.field === 'status') {
        el.addEventListener('change', async () => {
          const newStatus = el.value;
          if (COMMENT_REQ_STATUSES.has(newStatus)) {
            const comment = await _showStatusCommentModal(newStatus);
            if (comment === null) {
              // Revert
              const oldVal = el.dataset.originalValue || el.options[0].value;
              el.value = oldVal;
              return;
            }
            const res = await fetch(`/api/leads/${leadId}/change-status`, {
              method: 'POST',
              headers: { 'Content-Type': 'application/json' },
              body: JSON.stringify({ status: newStatus, comment }),
            });
            if (!res.ok) {
              const body = await res.json().catch(() => ({}));
              _showToast(body.message || 'Erro ao alterar status.', 'danger');
              el.value = el.dataset.originalValue || el.options[0].value;
              return;
            }
            el.dataset.originalValue = newStatus;
            if (window.LeadModal && window.LeadModal._reload) window.LeadModal._reload(leadId);
            else location.reload();
          } else {
            el.dataset.originalValue = newStatus;
            debouncedSave(el.dataset.field, newStatus);
          }
        });
        // Store current value
        el.dataset.originalValue = el.value;
      } else {
        el.addEventListener(evt, () => debouncedSave(el.dataset.field, el.value));
      }
    });

    // ---- Botão "Salvar" no header (salva manualmente todos os campos) ----
    const saveAllBtn = root.querySelector('.lead-save-all-btn');
    if (saveAllBtn) {
      saveAllBtn.addEventListener('click', () => {
        const payload = {};
        root.querySelectorAll('.lead-field').forEach(el => {
          payload[el.dataset.field] = el.value;
        });
        patchLead(leadId, payload).then(() => flashOk(root, 'Salvo!'));
      });
    }

    // ---- Op flags (Sim / Não) ----
    root.querySelectorAll('.op-flag-group').forEach(group => {
      if (group.dataset.disabled === 'true') return; // skip disabled groups
      group.querySelectorAll('.op-flag-btn').forEach(btn => {
        btn.addEventListener('click', () => {
          const field = group.dataset.field;
          const val   = btn.dataset.val;
          // Update UI
          group.querySelectorAll('.op-flag-btn').forEach(b => {
            b.classList.remove('btn-success', 'btn-danger', 'btn-outline-secondary');
            if (b.dataset.val === 'sim') b.classList.add('btn-outline-secondary');
            else b.classList.add('btn-outline-secondary');
          });
          if (val === 'sim') {
            btn.classList.remove('btn-outline-secondary');
            btn.classList.add('btn-success');
          } else {
            btn.classList.remove('btn-outline-secondary');
            btn.classList.add('btn-danger');
          }
          patchLead(leadId, { [field]: val }).then(() => {
            // If baixo_risco just set to sim, disable bombeiro/vigilância groups
            if (field === 'op_baixo_risco' && val === 'sim') {
              _disableBaixoRiscoGroups(root);
            }
            // Refresh to show/hide Órgãos tab if needed
            if (window.LeadModal && window.LeadModal._reload) window.LeadModal._reload(leadId);
            else location.reload();
          });
        });
      });
    });

    function _disableBaixoRiscoGroups(root) {
      ['op_bombeiro', 'op_vigilancia'].forEach(field => {
        const grp = root.querySelector(`.op-flag-group[data-field="${field}"]`);
        if (grp) {
          grp.dataset.disabled = 'true';
          grp.querySelectorAll('button').forEach(b => b.disabled = true);
          const label = grp.closest('.d-flex');
          if (label) {
            const span = label.querySelector('span.small');
            if (span && !span.querySelector('.badge')) {
              const badge = document.createElement('span');
              badge.className = 'badge bg-light text-muted border ms-1';
              badge.style.fontSize = '9px';
              badge.textContent = 'Dispensado';
              span.appendChild(badge);
            }
          }
        }
      });
    }

    // ---- Custom chat/history tabs ----
    root.querySelectorAll('.chat-tab-btn').forEach(btn => {
      btn.addEventListener('click', () => {
        const target = btn.dataset.target;
        root.querySelectorAll('.chat-tab-btn').forEach(b => {
          b.classList.remove('active-chat-tab');
          b.style.color = '#94a3b8';
          b.style.borderBottom = '2px solid transparent';
          b.style.fontWeight = '';
        });
        btn.classList.add('active-chat-tab');
        btn.style.color = '#1e293b';
        btn.style.borderBottom = '2px solid #1e293b';
        btn.style.fontWeight = '600';
        root.querySelectorAll('.chat-panel').forEach(p => {
          if (p.id === target) { p.classList.remove('d-none'); p.style.display = 'flex'; p.style.flexDirection = 'column'; }
          else { p.classList.add('d-none'); p.style.display = ''; }
        });
      });
    });

    // ---- Descrição: edit / save / cancel ----
    const descView      = root.querySelector('#descView');
    const descEdit      = root.querySelector('#descEdit');
    const descTextarea  = root.querySelector('#descTextarea');
    const descEditBtn   = root.querySelector('#descEditBtn');
    const descSaveBtn   = root.querySelector('#descSaveBtn');
    const descCancelBtn = root.querySelector('#descCancelBtn');
    if (descEditBtn) {
      descEditBtn.addEventListener('click', () => {
        descView.classList.add('d-none');
        descEdit.classList.remove('d-none');
        descTextarea.focus();
      });
    }
    if (descCancelBtn) {
      descCancelBtn.addEventListener('click', () => {
        descEdit.classList.add('d-none');
        descView.classList.remove('d-none');
      });
    }
    if (descSaveBtn) {
      descSaveBtn.addEventListener('click', async () => {
        const val = descTextarea.value;
        await patchLead(leadId, { description: val });
        descView.textContent = val || '— clique em editar para adicionar uma descrição —';
        descEdit.classList.add('d-none');
        descView.classList.remove('d-none');
        flashOk(root, 'Descrição salva!');
      });
    }

    // ---- Órgãos: salvar dados por órgão ----
    root.querySelectorAll('.organ-save-btn').forEach(btn => {
      btn.addEventListener('click', async () => {
        const organKey = btn.dataset.organ;
        const organData = {};
        root.querySelectorAll(`.organ-field[data-organ="${organKey}"]`).forEach(inp => {
          organData[inp.dataset.ofield] = inp.value;
        });
        // Load current op_organs_data, merge, save
        const lead = await fetch(`/api/leads/${leadId}`).then(r => r.json());
        let all = {};
        try { all = JSON.parse(lead.op_organs_data || '{}'); } catch(e) {}
        all[organKey] = organData;
        await patchLead(leadId, { op_organs_data: JSON.stringify(all) });
        flashOk(btn.closest('.card-body'), 'Salvo!');
      });
    });

    // ---- Tags (dropdown checkboxes) ----
    root.querySelectorAll('.tag-check').forEach(cb => {
      cb.addEventListener('change', () => {
        const ids = [...root.querySelectorAll('.tag-check:checked')].map(c => c.value);
        patchLead(leadId, { tag_ids: ids });
      });
    });

    // ---- Stage picker ----
    root.querySelectorAll('.stage-picker-container').forEach(host => {
      const stages = JSON.parse(host.dataset.stages || '[]');
      const current = host.dataset.current;
      const currentStageName = host.dataset.currentStageName || '';
      host.innerHTML = '';

      const sel = document.createElement('select');
      sel.className = 'form-select form-select-sm rounded-2 lead-stage-select';
      stages.forEach((st, i) => {
        const opt = document.createElement('option');
        opt.value = st.id;
        opt.textContent = `${i + 1}. ${st.name}` + (st.sla_days ? ` (SLA: ${st.sla_days}d)` : '');
        if (st.id === current) opt.selected = true;
        sel.appendChild(opt);
      });

      sel.addEventListener('change', async () => {
        const targetId = sel.value;
        const targetStage  = stages.find(s => s.id === targetId);
        const currentStage = stages.find(s => s.id === current);

        const targetPos  = targetStage ? targetStage.position : 0;
        const currentPos = currentStage ? currentStage.position : 0;
        const movingForward  = targetPos > currentPos;
        const movingBackward = targetPos < currentPos;
        const targetName  = targetStage ? targetStage.name : '';

        // --- Guard: moving forward from "Em Aprovação com Cliente" ---
        if (movingForward && currentStageName === 'Em Aprovação com Cliente') {
          const res = await _doMove(leadId, targetId, {});
          if (res.status === 409) {
            const body = await res.json();
            if (body.require === 'client_approval') {
              _showToast('Aguardando aprovação do cliente. Gere o link de aprovação na aba Operacional.', 'warning');
              sel.value = current; // revert
              return;
            }
          } else {
            const apiData = await res.json().catch(() => ({}));
            _afterMove(root, leadId, currentStageName, targetName, targetId, stages, apiData);
            return;
          }
        }

        // --- Guard: moving backward from guarded stage ---
        if (movingBackward && GUARDED_STAGES[currentStageName]) {
          const guardType = GUARDED_STAGES[currentStageName];
          const needsPassword = PASSWORD_STAGES.has(currentStageName);
          const justification = await _showJustificationModal(currentStageName, needsPassword);
          if (!justification) {
            sel.value = current; // user cancelled
            return;
          }
          const payload = {
            justification: justification.justification,
          };
          if (needsPassword) {
            payload.guard_password = justification.password;
          }
          const res = await _doMove(leadId, targetId, payload);
          if (res.status === 409) {
            const body = await res.json();
            _showToast(body.message || 'Operação bloqueada.', 'danger');
            sel.value = current;
            return;
          }
          const apiData = await res.json().catch(() => ({}));
          _afterMove(root, leadId, currentStageName, targetName, targetId, stages, apiData);
          return;
        }

        // Normal move
        const res = await _doMove(leadId, targetId, {});
        if (!res.ok) {
          const body = await res.json().catch(() => ({}));
          if (res.status === 409 && body.require === 'protocol_data') {
            _showToast(body.message || 'Preencha os dados do protocolo primeiro.', 'warning');
          } else if (res.status === 409 && body.require === 'checklist') {
            _showToast(body.message || 'Conclua o checklist antes de avançar.', 'danger');
            // Switch to checklist tab to show the user what's missing
            const chkTab = root.querySelector('[data-bs-target="#tab-check"]');
            if (chkTab) chkTab.click();
            // Highlight incomplete required items after a brief delay
            setTimeout(() => {
              root.querySelectorAll('#checklistHost .checklist-item').forEach(el => {
                const lbl = el.querySelector('.chk-label')?.textContent?.trim();
                const done = el.querySelector('input[type=checkbox]')?.checked;
                const req = el.dataset.required === '1';
                if (req && !done) el.classList.add('chk-required-alert');
              });
            }, 150);
          } else {
            _showToast(body.message || 'Erro ao mover.', 'danger');
          }
          sel.value = current;
          return;
        }
        const apiData = await res.json().catch(() => ({}));
        _afterMove(root, leadId, currentStageName, targetName, targetId, stages, apiData);
      });

      host.appendChild(sel);
    });

    // ---- Approval panel ----
    _initApprovalPanel(root, leadId);

    // ---- Comentários ----
    const cmtBtn       = root.querySelector('#addCommentBtn');
    const cmtInput     = root.querySelector('#newComment');
    const cmtList      = root.querySelector('#commentList');
    const cmtFileInput = root.querySelector('#commentAttachment');
    const cmtFileName  = root.querySelector('#commentAttachmentName');

    if (cmtFileInput && cmtFileName) {
      cmtFileInput.addEventListener('change', () => {
        cmtFileName.textContent = cmtFileInput.files[0]?.name || '';
      });
    }

    // ---- @mention autocomplete ----
    if (cmtInput) {
      _initMentionAutocomplete(cmtInput, root);
    }

    if (cmtBtn) {
      const send = async () => {
        const body = cmtInput.value.trim();
        const file = cmtFileInput?.files[0];
        if (!body && !file) return;

        let resData;
        if (file) {
          const fd = new FormData();
          fd.append('body', body || ' ');
          fd.append('attachment', file);
          const res = await fetch(`/api/leads/${leadId}/comments`, { method: 'POST', body: fd });
          resData = await res.json();
        } else {
          const res = await fetch(`/api/leads/${leadId}/comments`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ body }),
          });
          resData = await res.json();
        }

        const empty = cmtList.querySelector('.text-muted.text-center');
        if (empty) empty.remove();

        const div = document.createElement('div');
        div.className = 'comment-item mb-3';
        let html = `
          <div class="d-flex justify-content-between mb-1">
            <strong class="small">Você</strong>
            <small class="text-muted">${new Date().toLocaleString('pt-BR')}</small>
          </div>
          <div class="small" style="white-space:pre-wrap;">${escapeHtml(body)}</div>`;
        if (resData.attachment_name) {
          const isImage = (resData.attachment_mime || '').startsWith('image/');
          const url = `/api/leads/comment-attachment/${resData.attachment_key}`;
          html += isImage
            ? `<div class="mt-1"><a href="${url}" target="_blank"><img src="${url}" style="max-width:200px;max-height:150px;border-radius:6px;border:1px solid #e2e8f0;"></a></div>`
            : `<div class="mt-1"><a href="${url}" class="btn btn-sm btn-outline-secondary rounded-2" download="${escapeHtml(resData.attachment_name)}"><i class="bi bi-paperclip"></i> ${escapeHtml(resData.attachment_name)}</a></div>`;
        }
        div.innerHTML = html;
        // Prepend (newest first)
        if (cmtList.firstChild) cmtList.insertBefore(div, cmtList.firstChild);
        else cmtList.appendChild(div);
        cmtInput.value = '';
        if (cmtFileInput) { cmtFileInput.value = ''; cmtFileName.textContent = ''; }
      };
      cmtBtn.addEventListener('click', send);
      cmtInput.addEventListener('keydown', (e) => {
        if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); send(); }
      });
    }

    // ---- Checklist ----
    const checklistHost = root.querySelector('#checklistHost');
    if (checklistHost) renderChecklist(checklistHost, leadId);

    // ---- Arquivos ----
    const fileInput = root.querySelector('#fileInput');
    const fileList  = root.querySelector('#fileList');
    if (fileInput) {
      fileInput.addEventListener('change', async () => {
        const f = fileInput.files[0];
        if (!f) return;
        const fd = new FormData();
        fd.append('file', f);
        const res = await fetch(`/api/leads/${leadId}/files`, { method: 'POST', body: fd });
        if (!res.ok) { alert('Falha no upload.'); return; }
        const data = await res.json();
        const li = document.createElement('li');
        li.className = 'list-group-item d-flex justify-content-between align-items-center';
        li.dataset.fileId = data.id;
        li.innerHTML = `
          <div><i class="bi bi-file-earmark"></i>
            <a href="/api/leads/files/${data.id}">${data.filename}</a>
            <small class="text-muted ms-2">${(data.size_bytes / 1024).toFixed(1)} KB</small></div>
          <button class="btn btn-sm btn-link text-danger file-delete p-0"><i class="bi bi-trash"></i></button>`;
        const empty = fileList.querySelector('.text-muted.text-center');
        if (empty) empty.remove();
        fileList.appendChild(li);
        fileInput.value = '';
      });
    }
    if (fileList) {
      fileList.addEventListener('click', async (e) => {
        const btn = e.target.closest('.file-delete');
        if (!btn) return;
        const li = btn.closest('[data-file-id]');
        if (!confirm('Excluir este arquivo?')) return;
        await fetch(`/api/leads/files/${li.dataset.fileId}`, { method: 'DELETE' });
        li.remove();
      });
    }

    // ---- Excluir processo ----
    const delBtn = root.querySelector('.lead-delete-btn');
    if (delBtn) {
      delBtn.addEventListener('click', async () => {
        if (!confirm('Excluir este processo? Esta ação não pode ser desfeita.')) return;
        const delRes = await fetch(`/api/leads/${leadId}`, { method: 'DELETE' });
        if (!delRes.ok) return;
        if (window.LEAD_FULLPAGE) {
          location.href = '/leads?view=kanban';
        } else {
          // Remove lead from DOM without reload (avoids reopening deleted lead from URL ?card=)
          const wrapper = document.querySelector(
            `.kanban-closed-wrapper[data-lead-id="${leadId}"], .lead-row[data-lead-id="${leadId}"]`
          );
          if (wrapper) wrapper.remove();
          window.LeadModal?.close();
          // Update kanban column counts
          document.querySelectorAll('.kanban-col').forEach(col => {
            const body  = col.querySelector('.kanban-col-body');
            const badge = col.querySelector('.kanban-col-count');
            if (body && badge) {
              const total  = body.querySelectorAll('.kanban-card').length;
              const hidden = body.querySelectorAll('.kanban-card-closed').length;
              badge.textContent = total - hidden;
            }
          });
        }
      });
    }

    // ---- Fechar ----
    const closeBtn = root.querySelector('.card-modal-close');
    if (closeBtn && window.LEAD_FULLPAGE) {
      closeBtn.addEventListener('click', () => { location.href = '/leads?view=kanban'; });
    }

    // ---- URL Junta: edit / save / cancel (description-style) ----
    const juntaUrlEditBtn   = root.querySelector('#juntaUrlEditBtn');
    const juntaUrlView      = root.querySelector('#juntaUrlView');
    const juntaUrlEdit      = root.querySelector('#juntaUrlEdit');
    const juntaUrlInput     = root.querySelector('#juntaUrlInput');
    const juntaUrlSaveBtn   = root.querySelector('#juntaUrlSaveBtn');
    const juntaUrlCancelBtn = root.querySelector('#juntaUrlCancelBtn');
    if (juntaUrlEditBtn) {
      juntaUrlEditBtn.addEventListener('click', () => {
        juntaUrlView.classList.add('d-none');
        juntaUrlEdit.classList.remove('d-none');
        juntaUrlInput.focus();
      });
    }
    if (juntaUrlCancelBtn) {
      juntaUrlCancelBtn.addEventListener('click', () => {
        juntaUrlEdit.classList.add('d-none');
        juntaUrlView.classList.remove('d-none');
      });
    }
    if (juntaUrlSaveBtn) {
      juntaUrlSaveBtn.addEventListener('click', async () => {
        const url = juntaUrlInput.value.trim();
        await patchLead(leadId, { op_url_junta: url });
        if (url) {
          juntaUrlView.innerHTML = `<a href="${escapeHtml(url)}" target="_blank" rel="noopener" class="small text-primary d-inline-flex align-items-center gap-1" style="word-break:break-all;"><i class="bi bi-box-arrow-up-right flex-shrink-0"></i>${escapeHtml(url)}</a>`;
        } else {
          juntaUrlView.innerHTML = '<span class="small text-muted fst-italic">— clique no lápis para adicionar a URL —</span>';
        }
        juntaUrlEdit.classList.add('d-none');
        juntaUrlView.classList.remove('d-none');
        flashOk(juntaUrlSaveBtn.closest('.mb-3'), 'Salvo!');
      });
    }

    // ---- Link de Assinatura Junta Comercial: edit / save / cancel ----
    const assinaturaLinkEditBtn   = root.querySelector('#assinaturaLinkEditBtn');
    const assinaturaLinkView      = root.querySelector('#assinaturaLinkView');
    const assinaturaLinkEdit      = root.querySelector('#assinaturaLinkEdit');
    const assinaturaLinkInput     = root.querySelector('#assinaturaLinkInput');
    const assinaturaLinkSaveBtn   = root.querySelector('#assinaturaLinkSaveBtn');
    const assinaturaLinkCancelBtn = root.querySelector('#assinaturaLinkCancelBtn');
    if (assinaturaLinkEditBtn) {
      assinaturaLinkEditBtn.addEventListener('click', () => {
        assinaturaLinkView.classList.add('d-none');
        assinaturaLinkEdit.classList.remove('d-none');
        assinaturaLinkInput.focus();
      });
    }
    if (assinaturaLinkCancelBtn) {
      assinaturaLinkCancelBtn.addEventListener('click', () => {
        assinaturaLinkEdit.classList.add('d-none');
        assinaturaLinkView.classList.remove('d-none');
      });
    }
    if (assinaturaLinkSaveBtn) {
      assinaturaLinkSaveBtn.addEventListener('click', async () => {
        const url = assinaturaLinkInput.value.trim();
        await patchLead(leadId, { op_link_assinatura_junta: url });
        if (url) {
          assinaturaLinkView.innerHTML = `<a href="${escapeHtml(url)}" target="_blank" rel="noopener" class="small text-warning d-inline-flex align-items-center gap-1 fw-semibold" style="word-break:break-all;"><i class="bi bi-pen-fill flex-shrink-0"></i>${escapeHtml(url)}</a>`;
        } else {
          assinaturaLinkView.innerHTML = '<span class="small text-muted fst-italic">— clique no lápis para adicionar o link de assinatura —</span>';
        }
        assinaturaLinkEdit.classList.add('d-none');
        assinaturaLinkView.classList.remove('d-none');
        flashOk(assinaturaLinkSaveBtn.closest('.mb-3'), 'Salvo!');
      });
    }

    // ---- Portal do Cliente: Gerar link ----
    const portalGerarBtn = root.querySelector('#portalGerarBtn');
    const portalLinkInput = root.querySelector('#portalLinkInput');
    const portalCopyBtn = root.querySelector('#portalCopyBtn');
    if (portalGerarBtn) {
      portalGerarBtn.addEventListener('click', async () => {
        portalGerarBtn.disabled = true;
        portalGerarBtn.innerHTML = '<span class="spinner-border spinner-border-sm me-1"></span>Gerando…';
        try {
          const lid = portalGerarBtn.dataset.leadId;
          const res = await fetch(`/leads/${lid}/gerar-link-cliente`, { method: 'POST' });
          const data = await res.json();
          if (data.token) {
            const link = `${window.location.origin}/processo/${data.token}`;
            portalLinkInput.value = link;
            portalCopyBtn.disabled = false;
            portalGerarBtn.innerHTML = '<i class="bi bi-arrow-clockwise me-1"></i>Regerar link';
          }
        } catch(e) {
          portalGerarBtn.innerHTML = '<i class="bi bi-magic me-1"></i>Gerar link';
        }
        portalGerarBtn.disabled = false;
      });
    }
    if (portalCopyBtn) {
      portalCopyBtn.addEventListener('click', () => {
        if (!portalLinkInput.value) return;
        navigator.clipboard.writeText(portalLinkInput.value).then(() => {
          const orig = portalCopyBtn.innerHTML;
          portalCopyBtn.innerHTML = '<i class="bi bi-check-lg"></i>';
          setTimeout(() => { portalCopyBtn.innerHTML = orig; }, 1500);
        });
      });
    }

    // ---- "Ver processo pai" ----
    root.querySelectorAll('.open-parent-btn').forEach(btn => {
      btn.addEventListener('click', (e) => {
        e.stopPropagation();
        const lid = btn.dataset.leadId;
        if (lid && window.LeadModal) window.LeadModal.open(lid);
      });
    });

    // ---- Marcar como baixo risco (sugestão IA) ----
    const markBtn = root.querySelector('#markBaixoRiscoBtn');
    if (markBtn) {
      markBtn.addEventListener('click', async () => {
        markBtn.disabled = true;
        await patchLead(leadId, { op_baixo_risco: 'sim' });
        _showToast('Marcado como baixo risco — análise por IA.', 'success');
        if (window.LeadModal && window.LeadModal._reload) window.LeadModal._reload(leadId);
        else location.reload();
      });
    }

    // ---- Manual organ child creation buttons ----
    root.querySelectorAll('.create-organ-child-btn').forEach(btn => {
      btn.addEventListener('click', async () => {
        const organType = btn.dataset.organType;
        btn.disabled = true;
        btn.innerHTML = '<span class="spinner-border spinner-border-sm me-1"></span>Criando...';
        try {
          const res = await fetch(`/api/leads/${leadId}/create-organ-child`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ organ_type: organType }),
          });
          const data = await res.json();
          if (data.ok && data.created) {
            _showToast(`Card criado: ${data.created.organ}`, 'success');
            window.open(`/leads/${data.created.id}`, '_blank');
            if (window.LeadModal && window.LeadModal._reload) window.LeadModal._reload(leadId);
            else location.reload();
          } else if (data.ok && !data.created) {
            _showToast('Card já existente para este órgão.', 'warning');
            btn.disabled = false;
            btn.innerHTML = btn.dataset.originalLabel || 'Criar';
          } else {
            _showToast(data.error || 'Erro ao criar card.', 'danger');
            btn.disabled = false;
            btn.innerHTML = btn.dataset.originalLabel || 'Criar';
          }
        } catch (e) {
          _showToast('Erro ao criar card.', 'danger');
          btn.disabled = false;
          btn.innerHTML = btn.dataset.originalLabel || 'Criar';
        }
      });
      // Store original label for restore
      btn.dataset.originalLabel = btn.innerHTML;
    });

    // ---- Organ child card: save dados do órgão no processo pai ----
    const organChildSaveBtn = root.querySelector('.organ-child-save-btn');
    if (organChildSaveBtn) {
      const container = root.querySelector('[data-organ-card-key]');
      const organKey  = container?.dataset.organCardKey;
      const parentId  = container?.dataset.organParentId;
      organChildSaveBtn.addEventListener('click', async () => {
        if (!parentId || !organKey) {
          _showToast('Processo pai não encontrado.', 'danger');
          return;
        }
        const organData = {};
        root.querySelectorAll('.organ-child-field').forEach(inp => {
          organData[inp.dataset.ofield] = inp.value;
        });
        const parentLead = await fetch(`/api/leads/${parentId}`).then(r => r.json());
        let all = {};
        try { all = JSON.parse(parentLead.op_organs_data || '{}'); } catch(e) {}
        all[organKey] = organData;
        await patchLead(parentId, { op_organs_data: JSON.stringify(all) });
        flashOk(organChildSaveBtn.closest('.p-3.border'), 'Salvo!');
      });
    }

    // ---- Geração de documento por IA ----
    const iaDocGerarBtn = root.querySelector('#iaDocGerarBtn');
    if (iaDocGerarBtn) {
      iaDocGerarBtn.addEventListener('click', async () => {
        const contexto = root.querySelector('#iaDocContexto')?.value?.trim();
        if (!contexto) { _showToast('Informe o contexto do documento.', 'warning'); return; }
        iaDocGerarBtn.disabled = true;
        iaDocGerarBtn.innerHTML = '<span class="spinner-border spinner-border-sm me-1"></span>Gerando...';
        try {
          const res = await fetch(`/api/leads/${leadId}/gerar-documento-ia`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ contexto }),
          });
          const data = await res.json().catch(() => ({}));
          if (!res.ok) {
            _showToast(data.message || data.error || 'Erro ao gerar documento.', 'danger');
            return;
          }
          // Trigger download via file endpoint
          if (data.file_id) {
            const a = document.createElement('a');
            a.href = `/api/leads/files/${data.file_id}`;
            a.download = data.filename || 'documento_ia.docx';
            document.body.appendChild(a);
            a.click();
            a.remove();
            // Reload modal to show new file + comment
            if (window.LeadModal && window.LeadModal._reload) window.LeadModal._reload(leadId);
          }
          _showToast('Documento gerado e salvo nos arquivos!', 'success');
        } catch (e) {
          _showToast('Erro ao gerar documento.', 'danger');
        } finally {
          iaDocGerarBtn.disabled = false;
          iaDocGerarBtn.innerHTML = '<i class="bi bi-stars me-1"></i>Gerar e baixar documento (.docx)';
        }
      });
    }

    // ---- Form dinâmico (legado) ----
    const formEl = root.querySelector('#leadForm');
    if (formEl && window.DynamicForm) {
      const fields = JSON.parse(formEl.dataset.fields);
      const values = JSON.parse(formEl.dataset.values || '{}');
      window.DynamicForm.render(formEl.querySelector('#dynamicFormHost'), fields, values);
      formEl.addEventListener('submit', async (e) => {
        e.preventDefault();
        const payload = window.DynamicForm.collect(formEl.querySelector('#dynamicFormHost'), fields);
        const res = await fetch(`/api/leads/${leadId}/form`, {
          method: 'PUT',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify(payload),
        });
        if (res.ok) flashOk(formEl, 'Salvo!');
        else flashOk(formEl, 'Erro ao salvar', true);
      });
    }
  }

  // ---------------------------------------------------------------------------
  // Guard helpers
  // ---------------------------------------------------------------------------

  async function _doMove(leadId, stageId, extraPayload) {
    return fetch(`/api/leads/${leadId}/move`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ stage_id: stageId, ...extraPayload }),
    });
  }

  function _afterMove(root, leadId, fromStageName, toStageName, toStageId, stages, apiData) {
    apiData = apiData || {};
    // Handle post-junta advance: create organ leads
    // Use API flag when available, fall back to stage name check
    const needsJuntaModal = apiData.show_junta_modal != null
      ? apiData.show_junta_modal
      : (fromStageName === 'Protocolo na Junta Comercial');
    if (needsJuntaModal) {
      _showJuntaOrganModal(leadId);
    } else {
      if (window.LeadModal && window.LeadModal._reload) window.LeadModal._reload(leadId);
      else location.reload();
    }
  }

  function _showJustificationModal(stageName, needsPassword) {
    return new Promise((resolve) => {
      const overlay = document.createElement('div');
      overlay.style.cssText = 'position:fixed;inset:0;background:rgba(0,0,0,.5);z-index:9999;display:flex;align-items:center;justify-content:center;';
      const modal = document.createElement('div');
      modal.style.cssText = 'background:#fff;border-radius:12px;padding:24px;max-width:480px;width:90%;box-shadow:0 20px 60px rgba(0,0,0,.3);';
      modal.innerHTML = `
        <h5 class="fw-bold mb-1">Justificativa necessária</h5>
        <p class="text-muted small mb-3">Você está retrocedendo de <strong>${escapeHtml(stageName)}</strong>. Por favor, informe o motivo.</p>
        <div class="mb-3">
          <label class="form-label small fw-semibold">Justificativa <span class="text-danger">*</span></label>
          <textarea id="_justTa" class="form-control" rows="3" placeholder="Descreva o motivo do retrocesso..."></textarea>
        </div>
        ${needsPassword ? `
        <div class="mb-3">
          <label class="form-label small fw-semibold">Senha de Gerente/Admin <span class="text-danger">*</span></label>
          <input type="password" id="_justPwd" class="form-control" placeholder="Senha">
        </div>
        ` : ''}
        <div class="d-flex gap-2 justify-content-end">
          <button class="btn btn-secondary btn-sm" id="_justCancel">Cancelar</button>
          <button class="btn btn-danger btn-sm" id="_justConfirm">Confirmar retrocesso</button>
        </div>`;
      overlay.appendChild(modal);
      document.body.appendChild(overlay);

      overlay.querySelector('#_justCancel').addEventListener('click', () => {
        overlay.remove();
        resolve(null);
      });
      overlay.querySelector('#_justConfirm').addEventListener('click', () => {
        const j = overlay.querySelector('#_justTa').value.trim();
        const p = needsPassword ? (overlay.querySelector('#_justPwd')?.value || '') : '';
        if (!j) {
          overlay.querySelector('#_justTa').classList.add('is-invalid');
          return;
        }
        overlay.remove();
        resolve({ justification: j, password: p });
      });
    });
  }

  function _showJuntaOrganModal(leadId) {
    return new Promise((resolve) => {
      const overlay = document.createElement('div');
      overlay.style.cssText = 'position:fixed;inset:0;background:rgba(0,0,0,.5);z-index:9999;display:flex;align-items:center;justify-content:center;';
      const modal = document.createElement('div');
      modal.style.cssText = 'background:#fff;border-radius:12px;padding:24px;max-width:460px;width:90%;box-shadow:0 20px 60px rgba(0,0,0,.3);';
      modal.innerHTML = `
        <h5 class="fw-bold mb-2"><i class="bi bi-building-check me-2 text-success"></i>Processo na Junta</h5>
        <p class="text-muted mb-4">A Junta emitiu <strong>certidão de dispensa de licenças</strong>?</p>
        <p class="small text-muted mb-3">Se sim, bombeiro e vigilância sanitária serão dispensados automaticamente e apenas alvará e conselho de classe serão criados (se marcados).</p>
        <div class="d-flex gap-3 justify-content-center">
          <button class="btn btn-success btn-lg px-4" id="_juntaYes">
            <i class="bi bi-check-circle me-1"></i> Sim, tem dispensa
          </button>
          <button class="btn btn-outline-secondary btn-lg px-4" id="_juntaNo">
            <i class="bi bi-x-circle me-1"></i> Não
          </button>
        </div>`;
      overlay.appendChild(modal);
      document.body.appendChild(overlay);

      async function proceed(dispensa) {
        overlay.remove();
        try {
          const res = await fetch(`/api/leads/${leadId}/create-organ-leads`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ dispensa_licencas: dispensa }),
          });
          const data = await res.json();
          if (data.created && data.created.length > 0) {
            _showToast(`${data.created.length} cartão(ões) de órgão criado(s).`, 'success');
            // Open new tabs for each created organ lead
            data.created.forEach(c => {
              window.open(`/leads/${c.id}`, '_blank');
            });
          }
        } catch (e) {
          console.error(e);
        }
        if (window.LeadModal && window.LeadModal._reload) window.LeadModal._reload(leadId);
        else location.reload();
        resolve();
      }

      overlay.querySelector('#_juntaYes').addEventListener('click', () => proceed(true));
      overlay.querySelector('#_juntaNo').addEventListener('click', () => proceed(false));
    });
  }

  function _showToast(msg, type) {
    const t = document.createElement('div');
    t.className = `alert alert-${type} position-fixed shadow`;
    t.style.cssText = 'bottom:24px;right:24px;z-index:9999;max-width:360px;font-size:14px;';
    t.textContent = msg;
    document.body.appendChild(t);
    setTimeout(() => t.remove(), 3500);
  }

  // ---------------------------------------------------------------------------
  // Status comment modal (required for Cancelado / Inativo)
  // ---------------------------------------------------------------------------

  function _showStatusCommentModal(statusName) {
    return new Promise((resolve) => {
      const overlay = document.createElement('div');
      overlay.style.cssText = 'position:fixed;inset:0;background:rgba(0,0,0,.5);z-index:9999;display:flex;align-items:center;justify-content:center;';
      const modal = document.createElement('div');
      modal.style.cssText = 'background:#fff;border-radius:12px;padding:24px;max-width:480px;width:90%;box-shadow:0 20px 60px rgba(0,0,0,.3);';
      modal.innerHTML = `
        <h5 class="fw-bold mb-1">Alterar status para <span class="text-danger">${escapeHtml(statusName)}</span></h5>
        <p class="text-muted small mb-3">Informe o motivo. Este comentário será registrado no histórico do processo.</p>
        <div class="mb-3">
          <label class="form-label small fw-semibold">Motivo / Comentário <span class="text-danger">*</span></label>
          <textarea id="_statusCmtTa" class="form-control" rows="3" placeholder="Descreva o motivo..."></textarea>
        </div>
        <div class="d-flex gap-2 justify-content-end">
          <button class="btn btn-secondary btn-sm" id="_statusCmtCancel">Cancelar</button>
          <button class="btn btn-danger btn-sm" id="_statusCmtConfirm">Confirmar</button>
        </div>`;
      overlay.appendChild(modal);
      document.body.appendChild(overlay);
      overlay.querySelector('#_statusCmtCancel').addEventListener('click', () => {
        overlay.remove();
        resolve(null);
      });
      overlay.querySelector('#_statusCmtConfirm').addEventListener('click', () => {
        const val = overlay.querySelector('#_statusCmtTa').value.trim();
        if (!val) {
          overlay.querySelector('#_statusCmtTa').classList.add('is-invalid');
          return;
        }
        overlay.remove();
        resolve(val);
      });
    });
  }

  // ---------------------------------------------------------------------------
  // @mention autocomplete
  // ---------------------------------------------------------------------------

  let _usersCache = null;

  async function _getUsers() {
    if (_usersCache) return _usersCache;
    try {
      const data = await fetch('/api/leads/users-list').then(r => r.json());
      _usersCache = data || [];
    } catch(e) { _usersCache = []; }
    return _usersCache;
  }

  function _initMentionAutocomplete(textarea, root) {
    const dropdown = document.createElement('ul');
    dropdown.className = 'list-group position-absolute shadow';
    dropdown.style.cssText = 'z-index:10000;max-height:180px;overflow-y:auto;min-width:200px;display:none;background:#fff;border:1px solid #dee2e6;border-radius:8px;';
    textarea.parentElement.style.position = 'relative';
    textarea.parentElement.appendChild(dropdown);

    let mentionStart = -1;
    let selectedIdx = 0;
    let filteredUsers = [];

    function hideDrop() {
      dropdown.style.display = 'none';
      mentionStart = -1;
    }

    function showDrop(users) {
      filteredUsers = users;
      selectedIdx = 0;
      dropdown.innerHTML = '';
      if (users.length === 0) { hideDrop(); return; }
      users.forEach((u, i) => {
        const li = document.createElement('li');
        li.className = 'list-group-item list-group-item-action py-1 px-2 small';
        li.textContent = u.name;
        li.dataset.idx = i;
        li.addEventListener('mousedown', (e) => {
          e.preventDefault();
          insertMention(u.name);
        });
        dropdown.appendChild(li);
      });
      dropdown.style.display = 'block';
      updateSelected();
    }

    function updateSelected() {
      dropdown.querySelectorAll('li').forEach((li, i) => {
        li.classList.toggle('active', i === selectedIdx);
      });
    }

    function insertMention(name) {
      const val = textarea.value;
      const before = val.slice(0, mentionStart);
      const after = val.slice(textarea.selectionStart);
      textarea.value = before + '@' + name + ' ' + after;
      const pos = (before + '@' + name + ' ').length;
      textarea.setSelectionRange(pos, pos);
      hideDrop();
      textarea.focus();
    }

    textarea.addEventListener('input', async () => {
      const val = textarea.value;
      const pos = textarea.selectionStart;
      // Find last @ before cursor
      const textBefore = val.slice(0, pos);
      const lastAt = textBefore.lastIndexOf('@');
      if (lastAt === -1 || (lastAt > 0 && !/\s/.test(val[lastAt - 1]))) {
        hideDrop(); return;
      }
      const query = textBefore.slice(lastAt + 1);
      if (/\s/.test(query)) { hideDrop(); return; }
      mentionStart = lastAt;
      const users = await _getUsers();
      const filtered = users.filter(u => u.name.toLowerCase().includes(query.toLowerCase()));
      showDrop(filtered.slice(0, 8));
    });

    textarea.addEventListener('keydown', (e) => {
      if (dropdown.style.display === 'none') return;
      if (e.key === 'ArrowDown') {
        e.preventDefault();
        selectedIdx = Math.min(selectedIdx + 1, filteredUsers.length - 1);
        updateSelected();
      } else if (e.key === 'ArrowUp') {
        e.preventDefault();
        selectedIdx = Math.max(selectedIdx - 1, 0);
        updateSelected();
      } else if (e.key === 'Enter' || e.key === 'Tab') {
        if (filteredUsers[selectedIdx]) {
          e.preventDefault();
          insertMention(filteredUsers[selectedIdx].name);
        }
      } else if (e.key === 'Escape') {
        hideDrop();
      }
    });

    document.addEventListener('click', (e) => {
      if (!dropdown.contains(e.target) && e.target !== textarea) hideDrop();
    });
  }

  // ---------------------------------------------------------------------------
  // Approval panel
  // ---------------------------------------------------------------------------

  function _initApprovalPanel(root, leadId) {
    const panel = root.querySelector('#approvalPanel');
    const pickerHost = root.querySelector('.stage-picker-container');
    if (!panel || !pickerHost) return;

    const currentStageName = pickerHost.dataset.currentStageName || '';
    if (currentStageName !== 'Em Aprovação com Cliente') return;

    panel.style.display = '';

    const statusDiv = root.querySelector('#approvalStatus');
    const genBtn    = root.querySelector('#generateApprovalBtn');
    if (!genBtn) return;

    genBtn.addEventListener('click', async () => {
      genBtn.disabled = true;
      genBtn.textContent = 'Gerando...';
      try {
        const res = await fetch(`/api/leads/${leadId}/generate-approval`, { method: 'POST' });
        const data = await res.json();
        if (data.ok) {
          statusDiv.innerHTML = `
            <div class="alert alert-info py-2 px-3 mb-2 small">
              <strong>Link gerado!</strong><br>
              <a href="${escapeHtml(data.link)}" target="_blank" class="d-block text-truncate">${escapeHtml(data.link)}</a>
              <div class="mt-1">Código de acesso: <strong>${escapeHtml(data.access_code)}</strong></div>
            </div>
            <div class="d-flex gap-2">
              <button class="btn btn-sm btn-outline-primary" id="_copyApprovalLink">
                <i class="bi bi-clipboard me-1"></i>Copiar link
              </button>
              <button class="btn btn-sm btn-outline-secondary" id="_regenApproval">
                <i class="bi bi-arrow-clockwise me-1"></i>Novo link
              </button>
            </div>`;
          statusDiv.querySelector('#_copyApprovalLink')?.addEventListener('click', () => {
            navigator.clipboard.writeText(data.link).then(() => _showToast('Link copiado!', 'success'));
          });
          statusDiv.querySelector('#_regenApproval')?.addEventListener('click', () => {
            statusDiv.innerHTML = `<p class="small text-muted mb-2">Gere um link de aprovação para enviar ao cliente.</p>
              <button class="btn btn-sm btn-primary" id="generateApprovalBtn"><i class="bi bi-link-45deg me-1"></i>Gerar Link de Aprovação</button>`;
            _initApprovalPanel(root, leadId);
          });
        }
      } catch (e) {
        genBtn.disabled = false;
        genBtn.textContent = 'Gerar Link de Aprovação';
        _showToast('Erro ao gerar link.', 'danger');
      }
    });
  }

  // ---------------------------------------------------------------------------

  function flashOk(host, msg, isError) {
    const div = document.createElement('div');
    div.className = `alert alert-${isError ? 'danger' : 'success'} mt-2 py-1 px-2 small`;
    div.textContent = msg;
    host.appendChild(div);
    setTimeout(() => div.remove(), 1800);
  }

  // ---- Checklist render ----
  function renderChecklist(host, leadId) {
    let items = JSON.parse(host.dataset.items || '[]');
    const stages = JSON.parse(host.dataset.stages || '[]');
    const current = host.dataset.currentStage;
    const stageTemplates = JSON.parse(host.dataset.stageTemplates || '[]');

    // Determine which template labels are already applied
    function unappliedTemplates() {
      const existingLabels = new Set(items.map(i => i.label.trim().toLowerCase()));
      return stageTemplates.filter(t => !existingLabels.has(t.label.trim().toLowerCase()));
    }

    function paint() {
      const byStage = new Map();
      items.forEach(it => {
        const key = it.stage_id || '__none__';
        if (!byStage.has(key)) byStage.set(key, []);
        byStage.get(key).push(it);
      });
      const html = [];
      const stageOrder = [...stages, { id: '__none__', name: 'Sem etapa' }];
      stageOrder.forEach(st => {
        const list = byStage.get(st.id) || [];
        if (!list.length && st.id !== current) return;
        html.push(`<h6 class="text-muted small fw-bold mt-3">${st.name}</h6>`);
        list.forEach(it => {
          const reqBadge = it.required ? '<span class="badge bg-danger ms-1" style="font-size:9px;">Obrigatório</span>' : '';
          html.push(`
            <div class="form-check d-flex justify-content-between align-items-center checklist-item py-1 px-1 rounded" data-id="${it.id}" data-required="${it.required ? '1' : '0'}">
              <div class="d-flex align-items-center gap-1">
                <input class="form-check-input me-1 chk-toggle" type="checkbox" ${it.done ? 'checked' : ''}>
                <span class="chk-label" style="${it.done ? 'text-decoration:line-through;color:#94a3b8' : ''}">${escapeHtml(it.label)}</span>
                ${reqBadge}
              </div>
              <button class="btn btn-sm btn-link text-danger chk-del p-0"><i class="bi bi-x"></i></button>
            </div>`);
        });
      });

      // Unapplied stage templates section
      const pending = unappliedTemplates();
      if (pending.length > 0) {
        html.push(`
          <div class="mt-3 p-2 border rounded-2 bg-warning-subtle">
            <div class="d-flex justify-content-between align-items-center mb-2">
              <span class="small fw-bold text-warning-emphasis">
                <i class="bi bi-list-check me-1"></i>${pending.length} item(s) do checklist da etapa ainda não aplicado(s)
              </span>
              <button class="btn btn-sm btn-warning px-2 py-0" id="chkApplyAll" style="font-size:11px;">
                <i class="bi bi-lightning-charge-fill me-1"></i>Aplicar todos
              </button>
            </div>
            ${pending.map(t => `
              <div class="d-flex align-items-center justify-content-between py-1 border-bottom border-warning-subtle">
                <span class="small">${escapeHtml(t.label)}${t.required ? ' <span class="badge bg-danger ms-1" style="font-size:9px;">Obrigatório</span>' : ''}</span>
                <button class="btn btn-sm btn-outline-warning chk-apply-one px-2 py-0" data-label="${escapeHtml(t.label)}" data-required="${t.required || 0}" style="font-size:11px;">
                  <i class="bi bi-plus"></i>
                </button>
              </div>`).join('')}
          </div>`);
      }

      html.push(`
        <div class="d-flex gap-2 mt-3">
          <input type="text" class="form-control form-control-sm" id="chkNewLabel" placeholder="Novo item…">
          <select class="form-select form-select-sm" id="chkNewStage" style="max-width:180px">
            <option value="">(sem etapa)</option>
            ${stages.map(s => `<option value="${s.id}" ${s.id === current ? 'selected' : ''}>${s.name}</option>`).join('')}
          </select>
          <button class="btn btn-sm btn-primary" id="chkAdd">+</button>
        </div>`);
      host.innerHTML = html.join('');

      host.querySelectorAll('.chk-toggle').forEach(cb => {
        cb.addEventListener('change', async () => {
          const row = cb.closest('[data-id]');
          await fetch(`/api/leads/checklist/${row.dataset.id}`, {
            method: 'PATCH',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ done: cb.checked }),
          });
          const it = items.find(x => x.id === row.dataset.id);
          if (it) it.done = cb.checked ? 1 : 0;
          paint();
        });
      });
      host.querySelectorAll('.chk-del').forEach(b => {
        b.addEventListener('click', async () => {
          const row = b.closest('[data-id]');
          await fetch(`/api/leads/checklist/${row.dataset.id}`, { method: 'DELETE' });
          items = items.filter(x => x.id !== row.dataset.id);
          paint();
        });
      });

      // Apply all stage templates
      const applyAllBtn = host.querySelector('#chkApplyAll');
      if (applyAllBtn) {
        applyAllBtn.addEventListener('click', async () => {
          applyAllBtn.disabled = true;
          const res = await fetch(`/api/leads/${leadId}/apply-stage-checklist`, { method: 'POST' });
          const data = await res.json();
          if (data.items) { items = data.items; paint(); }
        });
      }

      // Apply single template item
      host.querySelectorAll('.chk-apply-one').forEach(btn => {
        btn.addEventListener('click', async () => {
          const label = btn.dataset.label;
          const req = parseInt(btn.dataset.required || '0');
          const res = await fetch(`/api/leads/${leadId}/checklist`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ label, stage_id: current || null, required: req }),
          });
          const data = await res.json();
          items.push({ id: data.id, label, stage_id: current || null, done: 0, required: req });
          paint();
        });
      });

      host.querySelector('#chkAdd').addEventListener('click', async () => {
        const label = host.querySelector('#chkNewLabel').value.trim();
        const stage_id = host.querySelector('#chkNewStage').value || null;
        if (!label) return;
        const res = await fetch(`/api/leads/${leadId}/checklist`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ label, stage_id }),
        });
        const data = await res.json();
        items.push({ id: data.id, label, stage_id, done: 0 });
        paint();
      });
    }
    paint();
  }

  function escapeHtml(s) {
    return String(s).replace(/[&<>"']/g, c => ({
      '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;'
    })[c]);
  }

  if (window.LeadModal) window.LeadModal._bindModalHandlers = bindModal;

  // Expose junta organ modal globally so kanban.js can trigger it after drag
  window.CardModal = window.CardModal || {};
  window.CardModal.showJuntaOrganModal = _showJuntaOrganModal;

  // Child lead cards — click to open in modal
  document.addEventListener('click', (e) => {
    const card = e.target.closest('.child-lead-card');
    if (!card) return;
    const lid = card.dataset.leadId;
    if (lid && window.LeadModal) window.LeadModal.open(lid);
  });

  document.addEventListener('DOMContentLoaded', () => {
    if (!window.LEAD_FULLPAGE) return;
    const inner = document.querySelector('.card-modal-inner');
    if (inner) bindModal(inner, inner.dataset.leadId);
  });
})();
