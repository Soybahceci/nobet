#!/bin/sh
# NÖBET — konteyner girişi (denetim bulgusu O-2)
#
# Şema, uygulama başlamadan ÖNCE yükseltilir. Eskiden bu adım elle
# yapılıyordu ve unutulduğunda API yarım bir şemaya karşı açılıp
# `healthy` raporluyordu.
#
# `set -e`: migration başarısızsa konteyner AÇILMAZ. Yanlış şemayla
# çalışan bir API, açılmayan bir API'den daha tehlikelidir — hata
# aylar sonra bir tabloya ilk dokunulduğunda çıkar.
set -e

python -m app.migrate

# CMD (uvicorn ya da `python -m app.ingest`) buradan devralır.
exec "$@"
