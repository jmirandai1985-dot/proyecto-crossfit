"""Solo lectura: verifica 0 leftovers del harness TEST_AUDIT_ADMIN (S1/S2)."""
from sqlalchemy import create_engine, text
from app.core.config import settings

e = create_engine(settings.DATABASE_URL)
c = e.connect()
checks = [
    ("tenants", "SELECT COUNT(*) FROM tenants WHERE subdomain LIKE 'test-audit-admin-%'"),
    ("usuarios", "SELECT COUNT(*) FROM usuarios WHERE correo LIKE 'test_audit_admin_%' OR rut LIKE 'TAA%'"),
    ("solicitudes_planes",
     "SELECT COUNT(*) FROM solicitudes_planes s JOIN usuarios u ON u.id = s.alumno_id WHERE u.rut LIKE 'TAA%'"),
    ("suscripciones",
     "SELECT COUNT(*) FROM suscripciones s JOIN usuarios u ON u.id = s.usuario_id WHERE u.rut LIKE 'TAA%'"),
    ("planes", "SELECT COUNT(*) FROM planes p JOIN tenants t ON t.id = p.tenant_id WHERE t.subdomain LIKE 'test-audit-admin-%'"),
    ("notificaciones",
     "SELECT COUNT(*) FROM notificaciones n JOIN usuarios u ON u.id = n.alumno_id WHERE u.rut LIKE 'TAA%'"),
    ("transacciones_financieras",
     "SELECT COUNT(*) FROM transacciones_financieras tf JOIN tenants t ON t.id = tf.tenant_id WHERE t.subdomain LIKE 'test-audit-admin-%'"),
    ("auditoria",
     "SELECT COUNT(*) FROM auditoria a JOIN tenants t ON t.id = a.tenant_id WHERE t.subdomain LIKE 'test-audit-admin-%'"),
]
total = 0
for nombre, sql in checks:
    n = c.execute(text(sql)).scalar()
    print(f"[leftovers] {nombre}: {n}")
    total += n
c.close()
print(f"TOTAL leftovers: {total}")
