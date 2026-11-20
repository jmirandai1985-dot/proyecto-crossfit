"""
Reset del padrón de BoxMagic: 96 candidatos con correo + 4 sin correo (NULL).

Uso (SIEMPRE contra TEST):
    $env:ENVIRONMENT='test'; py -3.12 backend/scripts/reset_candidatos_boxmagic.py

Notas:
- El import real del proyecto es `app.db.database` (no `app.database`).
- Confirmación manual (`SI`) antes de borrar y recargar candidatos.
- Los 4 candidatos sin correo requieren la migración 090 (correo nullable).
- `tokens_migracion_boxmagic` requiere la migración 089 aplicada en TEST.
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from app.core.config import settings  # noqa: E402
from app.db.database import SessionLocal  # noqa: E402
from app.models.candidato_boxmagic import CandidatoBoxmagic  # noqa: E402
from app.models.token_migracion_boxmagic import TokenMigracionBoxmagic  # noqa: E402,F401
from sqlalchemy import text  # noqa: E402

print("ATENCION: esto va a borrar y recargar candidatos_boxmagic en la BD actual.")
print(f"DATABASE_URL: {settings.DATABASE_URL[:60]}...")
confirmacion = input("Escribe SI para continuar: ")
if confirmacion.strip() != "SI":
    print("Cancelado.")
    exit(0)

db = SessionLocal()
try:
    db.execute(text("DELETE FROM tokens_migracion_boxmagic"))
    db.execute(text("DELETE FROM candidatos_boxmagic"))
    db.execute(text("ALTER SEQUENCE candidatos_boxmagic_id_seq RESTART WITH 1"))

    from app.models.tenant import Tenant
    # `first()` sin ORDER BY no es determinista: en TEST hay dos tenants y devolvió
    # el 2 (vacío). El box real es el más antiguo (tenant 1), donde viven los admins,
    # alumnos, clases y suscripciones.
    tenant_id = db.query(Tenant).order_by(Tenant.id.asc()).first().id

    candidatos = [
        ('Ernesto  Urrutia', 'erurrutia03@gmail.com'),
        ('rodrigo huenchul', 'rodrigohuenchulg@gmail.com'),
        ('Nicolás Vejar', 'nicolas.arminvm@gmail.com'),
        ('Annette Palma', 'annette.vero@hotmail.com'),
        ('Isabel Hernandez', 'isahernandezcabrales@gmail.com'),
        ('Claudio Herrera', 'ce.herrerar@gmail.com'),
        ('Jorge Cordova', 'jorgeicg1517@gmail.com'),
        ('Claudia beatriz  Fuentes arriagada', 'dreamer.modas@gmail.com'),
        ('Esteban Muñoz Flores', 'floresmunozeste@gmail.com'),
        ('Flavio Pacheco', 'flavio.pachecomena@gmail.com'),
        ('JUAN PABLO CERDA BUENO', 'jpcerda.bueno@gmail.com'),
        ('Felipe Aguirre', 'felipeaguirregutierrez@gmail.com'),
        ('Valentina  Quiroz Tapia', 'valentinaq.tapia@gmail.com'),
        ('Jose Luis  Tapia figueroa', 'jtf.personal@gmail.com'),
        ('Daniel  Cisternas Fuentes', 'dcisternasfuentes@gmail.com'),
        ('Cristian Jimenez', 'cristianp.jimenezr@gmail.com'),
        ('Cristhoper Cordero', 'cristhoper.cordero.r@gmail.com'),
        ('Berenice  Alegria trujillo', 'bere.alegriat@gmail.com'),
        ('Carolina  Araneda', 'aranedab2@gmail.com'),
        ('David  Fuentes', 'dfuentesinostroza.i@gmail.com'),
        ('Patricio Vega', 'patriciovega188@gmail.com'),
        ('Camila  Allendes', 'camilallendesm@gmail.com'),
        ('Israel Vargas', 'israel.vargases@gmail.com'),
        ('Francisca Cisternas', 'francisterojas2813@gmail.com'),
        ('ALEXIS CANEO', 'alexis.caneo@gmail.com'),
        ('Katherine  Rivera Ramos', 'katherinea.r.r@hotmail.com'),
        ('Cristian Mellado', 'melladosoto.c@gmail.com'),
        ('Sandra Maulén Rocuant', 'smaulen13@gmail.com'),
        ('Claudia  Sasso', 'clauandrea.sasso@gmail.com'),
        ('Francisca  Fernanda', 'francisca.lazcano15@gmail.com'),
        ('Rosa Barraza', 'rosa.barraza.pedreros@gmail.com'),
        ('Alex Méndez', 'alex.mendez@live.cl'),
        ('Margarita Vergara', 'bmvergaras@gmail.com'),
        ('Inguibor  Rivera', 'iriverats@gmail.com'),
        ('Denisse Espinoza Lara', 'denissespinoza@hotmail.com'),
        ('Constanza Jael Alvarez Medina', 'c.alvarez.m01@gmail.com'),
        ('Franco Valenzuela', 'franco.valenzuela.e@gmail.com'),
        ('Patricio Serrano', 'patricio.serrano.psm@gmail.com'),
        ('Catalina Urra', 'catalina.urra@gmail.com'),
        ('Patricia  Echeverria', 'echeverriareyesp46@gmail.com'),
        ('Paulo Lillo', 'paulo.lillo.es@gmail.com'),
        ('Luisana  Navas', 'luisananavas557@gmail.com'),
        ('Carlos  Ovalle', 'carlos.ovalle.castillo@gmail.com'),
        ('Lorenzo Fuentes', 'lorenzofuentes7@gmail.com'),
        ('Constanza  Basualto', 'cono.basualto7@gmail.com'),
        ('Jorge antonio Aedo cuevas', 'aedocuevasj@gmail.com'),
        ('Abel Reyes Rubio', 'contacto.abelreyes@gmail.com'),
        ('Abraham  Messina', 'abrahammessina370@gmail.com'),
        ('Camila Moreno', 'camila.moreno.g.cm@gmail.com'),
        ('fabian delarze rojas', 'fabo.delarze@gmail.com'),
        ('Bryan Flores', 'bryanfloresh@gmail.com'),
        ('Viviana  Arevalo', 'viviana.arevalo.m@gmail.com'),
        ('Daniela  Rodríguez', 'daniela.rodriguez.fuentes@gmail.com'),
        ('Carlos  Durán', 'djmega.carlos@gmail.com'),
        ('Nilza Osorio', 'nilzaosoriom@gmail.com'),
        ('Gonzalo Alonso  Muñoz', 'gonzalo_munoz@live.cl'),
        ('David Alejandro Mandujano Muñoz', 'mandujano.david@gmail.com'),
        ('Nicolle Castilla', 'nicolle_tomas@hotmail.com'),
        ('Sandy  Mendez', 'sandymendez192@gmail.com'),
        ('Gustavo Miranda', 'g.mirandameza@gmail.com'),
        ('Leonardo Mardones', 'mardonesleonardo420@gmail.com'),
        ('Millaray  Berríos', 'millaray.20.02.01@gmail.com'),
        ('Roberto Pinto Aravena', 'roberto.pinto.em@gmail.com'),
        ('Paola  Salinas', 'paolaximenasalinas8@gmail.com'),
        ('Angélica  Retamales', 'angelica.retamales@bicevida.cl'),
        ('Boris Quilaqueo', 'borisquilaqueo.72@gmail.com'),
        ('Víctor  Torres', 'victor01feb@gmail.com'),
        ('Elizabeth  Perez', 'elyta11@gmail.com'),
        ('Melanie  Santana', 'mel.rosantana@gmail.com'),
        ('Luciano Toledo', 'lucianotoledoosorio1@gmail.com'),
        ('Catalina Ubilla', 'cataa.u24@gmail.com'),
        ('Roberto  Flores', 'santibanezrobertoflores@gmail.com'),
        ('Paul Ferrer', 'ferrerandres010@gmail.com'),
        ('Maria Florencia  Martinez Garrido', 'mfmartinezgarrido@gmail.com'),
        ('Paulo  Cortes', 'paulo.cortes.carrasco@gmail.com'),
        ('Cristobal Tapia', 'tapiacristobal3@gmail.com'),
        ('Matias Carmona', 'maticarmonarivera@gmail.com'),
        ('Jessica  Rojas', 'jekkrc@gmail.com'),
        ('Katherine Lorena  Solar Riquelme', 'asiriscosmos@gmail.com'),
        ('Larry Aguilar', 'larrytotal@hotmail.com'),
        ('Felipe  Fernández', 'felipefernandezsalinas226@gmail.com'),
        ('Javkeda  Palma', 'javierapalmaa@hotmail.com'),
        ('Jenny Miranda', 'jemihu68@gmail.com'),
        ('abraham olivares', 'eu.logy@hotmail.com'),
        ('Jose Arteaga', 'nixon.jaag@gmail.com'),
        ('Belen Sepúlveda', 'belsl1898@gmail.com'),
        ('Jorge Troncoso', 'jorge.troncoso11@gmail.com'),
        ('Natalia  Valdés González', 'natalia.valdes.gonzalez@gmail.com'),
        ('Escarly Bracho', 'escarlybracho1@gmail.com'),
        ('GIANFRANCO CARO', 'gcaroesquivel@gmail.com'),
        ('Erik  Aguilar León', 'erikaguilarleon@hotmail.com'),
        ('Ariel Aguilar', 'arielaguilarc01@gmail.com'),
        ('David González', 'david.gonzalez1983@gmail.com'),
        ('Camila  Lavin nuñez', 'camilanl18@gmail.com'),
        ('Annette  Palma', 'annette.palma.h@gmail.com'),
        ('Javier Quintreman', 'javierquintreman@gmail.com'),
        ('Yoslany Zuñiga', None),
        ('Javiera Rebolledo', None),
        ('Jacqueline Navarro', None),
        ('Vicente Jara', None),
    ]

    for nombre, correo in candidatos:
        db.add(CandidatoBoxmagic(
            tenant_id=tenant_id,
            nombre=nombre,
            correo=correo,
            estado_boxmagic='Activo',
            grupo='activacion'
        ))

    db.commit()
    total = db.query(CandidatoBoxmagic).count()
    print(f"OK — candidatos cargados: {total}")
finally:
    db.close()
