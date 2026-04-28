import sqlite3
import uuid
import os

DB_PATH = os.path.join(os.path.dirname(__file__), "contratos.db")

def new_id():
    return str(uuid.uuid4())

def main():
    conn = sqlite3.connect(DB_PATH)
    conn.execute("PRAGMA foreign_keys = ON")
    
    # 1. Delete all leads and fictional data
    print("Deleting all leads...")
    conn.execute("DELETE FROM leads") # Due to CASCADE, this deletes forms, comments, etc.
    conn.execute("DELETE FROM lead_types") # Due to CASCADE, this deletes workflows, macrophases, stages, etc.
    
    # 2. Re-create the lead type
    type_id = new_id()
    conn.execute(
        "INSERT INTO lead_types (id,name,color,active) VALUES (?,?,?,1)",
        (type_id, "Abertura de Empresa", "#2456a4"),
    )
    wf_id = new_id()
    conn.execute(
        "INSERT INTO lead_workflows (id,lead_type_id,name,is_default) VALUES (?,?,?,?)",
        (wf_id, type_id, "Padrão", 1),
    )
    
    mp_specs = [
        ("TRIAGEM E VIABILIDADE", 15, [
            ("1. Coleta de Informações", 3),
            ("2. Pedido de Viabilidade", 5),
            ("3. Análise da Prefeitura", 7),
        ]),
        ("PRODUÇÃO E APROVAÇÃO", 16, [
            ("4. Elaboração FCN e DBE", 3),
            ("5. Redação de Contrato", 3),
            ("6. Conferência Interna", 2),
            ("7. Validação e Pagamento", 3),
            ("8. Assinatura do Cliente", 5),
        ]),
        ("TRÂMITE JUNTA", 7, [
            ("9. Protocolo na Junta", 2),
            ("10. Em Exigência (Correções)", 5),
        ]),
        ("FINALIZAÇÃO", 21, [
            ("11. Inscrições Fiscais", 5),
            ("12. Licenças e Alvarás", 10),
            ("13. Setup Contábil", 3),
            ("14. Arquivo de Documentos", 2),
            ("15. Comunicado de Conclusão", 1),
        ]),
    ]
    
    stage_pos = 0
    for mp_pos, (mp_name, mp_sla, stages) in enumerate(mp_specs):
        mp_id = new_id()
        conn.execute(
            "INSERT INTO lead_macrophases (id,workflow_id,name,position,sla_days) VALUES (?,?,?,?,?)",
            (mp_id, wf_id, mp_name, mp_pos, mp_sla),
        )
        for st_name, st_sla in stages:
            conn.execute(
                "INSERT INTO lead_stages (id,workflow_id,macrophase_id,name,position,sla_days) "
                "VALUES (?,?,?,?,?,?)",
                (new_id(), wf_id, mp_id, st_name, stage_pos, st_sla),
            )
            stage_pos += 1

    conn.commit()
    conn.close()
    print("Stages updated properly.")

if __name__ == '__main__':
    main()
