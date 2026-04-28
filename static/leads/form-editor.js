/* Editor visual de campos do formulário (admin/formularios.html).
 * Cria/remove campos, edita label/tipo/obrigatório/seção e, para repeater,
 * permite adicionar sub-campos.  Salva tudo via hidden input fields_json.
 */

(function () {
  const host = document.getElementById('fieldsHost');
  const jsonHolder = document.getElementById('fieldsJson');
  const addBtn = document.getElementById('addFieldBtn');
  if (!host || !jsonHolder) return;

  const TYPES = [
    ['text', 'Texto'],
    ['number', 'Número'],
    ['date', 'Data'],
    ['textarea', 'Texto longo'],
    ['select', 'Lista (select)'],
    ['radio', 'Radio'],
    ['repeater', 'Repetidor (lista de itens)'],
    ['select_cnae', 'Autocomplete CNAE'],
  ];

  let fields = (window.LEADS_INITIAL_FIELDS || []).map(f => ({
    field_key:  f.field_key,
    label:      f.label,
    field_type: f.field_type,
    options:    f.options,
    required:   !!f.required,
    section:    f.section || 'Geral',
    help_text:  f.help_text || '',
  }));

  function paint() {
    host.innerHTML = '';
    fields.forEach((f, idx) => host.appendChild(rowEl(f, idx)));
    if (!fields.length) {
      host.innerHTML = '<div class="text-muted text-center py-4">Nenhum campo. Clique em <strong>Adicionar campo</strong>.</div>';
    }
  }

  function rowEl(f, idx) {
    const row = document.createElement('div');
    row.className = 'field-row' + (f.field_type === 'repeater' ? ' is-repeater' : '');
    row.innerHTML = `
      <div class="row g-2 align-items-end">
        <div class="col-md-3">
          <label class="form-label small text-muted">Label</label>
          <input class="form-control form-control-sm" data-prop="label" value="">
        </div>
        <div class="col-md-2">
          <label class="form-label small text-muted">Chave</label>
          <input class="form-control form-control-sm" data-prop="field_key" value="">
        </div>
        <div class="col-md-2">
          <label class="form-label small text-muted">Tipo</label>
          <select class="form-select form-select-sm" data-prop="field_type">
            ${TYPES.map(([k,l]) => `<option value="${k}">${l}</option>`).join('')}
          </select>
        </div>
        <div class="col-md-2">
          <label class="form-label small text-muted">Seção</label>
          <input class="form-control form-control-sm" data-prop="section" value="Geral">
        </div>
        <div class="col-md-1 d-flex align-items-end">
          <div class="form-check"><input type="checkbox" class="form-check-input" data-prop="required">
            <label class="form-check-label small">Obrig.</label></div>
        </div>
        <div class="col-md-2 d-flex align-items-end gap-1">
          <button class="btn btn-sm btn-outline-danger" type="button" data-action="remove" title="Excluir">
            <i class="bi bi-trash"></i>
          </button>
        </div>
        <div class="col-12 options-host"></div>
      </div>`;

    row.querySelector('[data-prop="label"]').value      = f.label || '';
    row.querySelector('[data-prop="field_key"]').value  = f.field_key || '';
    row.querySelector('[data-prop="field_type"]').value = f.field_type || 'text';
    row.querySelector('[data-prop="section"]').value    = f.section || 'Geral';
    row.querySelector('[data-prop="required"]').checked = !!f.required;

    row.querySelectorAll('[data-prop]').forEach(inp => {
      inp.addEventListener('input', () => {
        const prop = inp.dataset.prop;
        fields[idx][prop] = (prop === 'required') ? inp.checked : inp.value;
        if (prop === 'field_type') paint();  // re-render para ajustar options-host
      });
    });
    row.querySelector('[data-action="remove"]').addEventListener('click', () => {
      if (confirm('Remover este campo?')) {
        fields.splice(idx, 1);
        paint();
      }
    });

    // Options host depende do tipo
    const oh = row.querySelector('.options-host');
    if (f.field_type === 'select' || f.field_type === 'radio') {
      const ta = document.createElement('textarea');
      ta.className = 'form-control form-control-sm mt-2';
      ta.rows = 2;
      ta.placeholder = 'Uma opção por linha';
      ta.value = (f.options || []).map(o => typeof o === 'string' ? o : o.label).join('\n');
      ta.addEventListener('input', () => {
        fields[idx].options = ta.value.split('\n').map(s => s.trim()).filter(Boolean);
      });
      const lbl = document.createElement('label');
      lbl.className = 'form-label small text-muted mt-2';
      lbl.textContent = 'Opções';
      oh.appendChild(lbl); oh.appendChild(ta);
    } else if (f.field_type === 'repeater') {
      oh.appendChild(repeaterEditor(f, idx));
    }

    return row;
  }

  function repeaterEditor(field, parentIdx) {
    const wrap = document.createElement('div');
    wrap.className = 'mt-2';
    const lbl = document.createElement('label');
    lbl.className = 'form-label small text-muted';
    lbl.textContent = 'Sub-campos do repetidor';
    wrap.appendChild(lbl);

    const list = document.createElement('div');
    list.className = 'd-flex flex-column gap-1';
    wrap.appendChild(list);

    function paintSub() {
      list.innerHTML = '';
      (field.options || []).forEach((sf, i) => {
        const r = document.createElement('div');
        r.className = 'd-flex gap-1';
        r.innerHTML = `
          <input class="form-control form-control-sm" placeholder="Label" value="${esc(sf.label || '')}">
          <input class="form-control form-control-sm" placeholder="Chave" value="${esc(sf.key || '')}">
          <select class="form-select form-select-sm">
            ${TYPES.map(([k,l]) => `<option value="${k}" ${sf.type===k?'selected':''}>${l}</option>`).join('')}
          </select>
          <button class="btn btn-sm btn-outline-danger" type="button"><i class="bi bi-x"></i></button>`;
        const [lab, key, sel, del] = r.children;
        lab.addEventListener('input', () => { field.options[i].label = lab.value; });
        key.addEventListener('input', () => { field.options[i].key   = key.value; });
        sel.addEventListener('change', () => { field.options[i].type = sel.value; });
        del.addEventListener('click', () => { field.options.splice(i,1); paintSub(); });
        list.appendChild(r);
      });
      const add = document.createElement('button');
      add.type = 'button';
      add.className = 'btn btn-sm btn-outline-primary mt-1';
      add.innerHTML = '<i class="bi bi-plus"></i> sub-campo';
      add.addEventListener('click', () => {
        field.options = field.options || [];
        field.options.push({ label: '', key: '', type: 'text' });
        paintSub();
      });
      list.appendChild(add);
    }
    field.options = field.options || [];
    paintSub();
    return wrap;
  }

  function esc(s) {
    return String(s || '').replace(/"/g, '&quot;');
  }

  // botão adicionar
  addBtn.addEventListener('click', () => {
    fields.push({
      field_key: 'campo_' + (fields.length + 1),
      label: 'Novo campo',
      field_type: 'text',
      section: 'Geral',
      required: false,
    });
    paint();
  });

  // ao submeter, serializa
  document.querySelector('form').addEventListener('submit', () => {
    jsonHolder.value = JSON.stringify(fields);
  });

  paint();
})();
