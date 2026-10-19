from pymongo.database import Database

from app.db.bascula_repo import sum_net_weight_by_mineral
from app.models.bascula import MineralTotal


def get_mineral_totals(database: Database) -> list[MineralTotal]:
    totals = sum_net_weight_by_mineral(database)
    return [
        MineralTotal(
            mineral=total['_id'],
            producto=total.get('producto'),
            total=total['total'],
            fecha_subida=total.get('fechaSubida'),
            paquetes=total['paquetes'],
        )
        for total in totals
    ]