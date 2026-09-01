# Prob-Edge hacia Gamma Exposure: estudio de mercado, fuente primaria y requerimientos técnicos

Martes 1 de septiembre de 2026, 02:30 UTC (20:30 CST del 31 de agosto).
Documento de decisión, no de implementación.

---

## 0. Veredicto en una página

**El movimiento hacia GEX es defendible, pero no como lo planteaste.** "Hacer lo que hace SpotGamma o Unusual Whales" es entrar en el segmento más saturado del mercado de datos de opciones minorista, contra al menos cuarenta operadores, cinco de ellos ya en español, con un precio de entrada de USD 7 mensuales y un techo gratuito puesto por Barchart. La diferenciación por idioma, que era el eje del plan de agosto, ya no existe en esta categoría.

**Tres hallazgos gobiernan la decisión:**

**Primero. El nicho hispanohablante de GEX ya está ocupado.** GEXfocus vende cadena US diferida 15 minutos con GEX, vanna, charm, heatmaps y apps iOS y Android por USD 7 mensuales, y flujo en vivo cada 10 a 15 segundos por USD 30. GammaContext entrega WebSocket con latencia menor a 200 ms, DEX y GEX por strike, convexidad, vanna, charm y plugin nativo de NinjaTrader 8 por USD 49 mensuales, USD 39 anualizado. Ambos están por debajo del tier Trader de USD 39 que propone tu plan, con más funcionalidad y con latencia que tu arquitectura actual no puede igualar. El comparable de precio dejó de ser Opción Sigma a USD 39.99.

**Segundo. El costo de datos del producto que realmente diferencia es prohibitivo a tu escala.** El GEX ingenuo necesita interés abierto, que tu ruta actual no entrega y que además no puedes redistribuir. El GEX que sí mide algo (posicionamiento real del dealer, no una convención de signo) necesita datos etiquetados por participante de Cboe y Nasdaq. La aritmética: Cboe Open-Close EOD USD 600 mensuales más USD 5,000 por distribución externa de datos derivados, Nasdaq ISE Trade Outline USD 850 más USD 4,500 por lo mismo, más la cuota de redistribuidor de OPRA de USD 1,500. Total aproximado USD 12,700 mensuales, con cobertura de 10 de las 17 bolsas de opciones. El punto de equilibrio se mueve a 340 suscriptores en el tier Trader. Ese es el precio de admisión a la única versión del producto que no es una convención disfrazada de medición.

**Tercero. Ya tienes el activo que ningún competidor de este mercado publica.** Tu `rnd_forward.py` recupera una densidad neutral al riesgo bajo medida forward, con forward extraído por cruce call-put, sonrisa ajustada por mínimos cuadrados ponderados y diagnósticos publicables: integral 1.0000, R² de sonrisa 0.991 a 0.999, masa capturada 0.982 a 0.995. Revisé los cuarenta y tantos operadores del sector: **ninguno publica una densidad de riesgo neutral completa.** Publican niveles. La densidad es el objeto que tú ya sabes construir y que ellos no venden.

**La conclusión estratégica es una inversión del planteamiento:** no evolucionar Prob-Edge a GEX, sino incorporar GEX como la segunda capa de un producto cuya primera capa (la densidad) es el diferenciador. El eje de venta deja de ser "GEX en español" y pasa a ser "la única herramienta que muestra simultáneamente qué probabilidad asigna el mercado a cada precio y dónde está el flujo de cobertura que va a defender o romper esos niveles". Esa posición está vacía.

---

## 1. Cómo está segmentado el mercado en realidad

Seis bandas de precio, con densidad muy desigual de competidores.

| Segmento | Rango mensual | Quién está | Qué compra el cliente |
|---|---|---|---|
| Gratuito y captación | USD 0 | Barchart (declara feed OPRA consolidado, retraso 25 a 30 min), gammaibex (IBEX), AlgoStorm, FlashAlpha Free, ZeroGEX Free, OptionCharts, MenthorQ Free | GEX de fin de día o diferido, sin metodología |
| Overlay de gráfico | USD 7 a 30 | GEX Levels (9.99), **GEXfocus (7 y 30)**, **Gammetric (29.95)** | Niveles dibujados sobre TradingView o NinjaTrader |
| Retail generalista | USD 50 a 130 | Unusual Whales (50 a 120), Cheddar Flow (85 a 99), BlackBoxStocks (59 a 149), MenthorQ Premium (129), GEXBoard (39 a 149), **Tradeknowlogy (89)**, **GammaContext (49 a 99)** | GEX como una función más dentro de una plataforma de flujo |
| Especialista GEX | USD 199 a 400 | SpotGamma Alpha (299), OptionsDepth (199 a 249), Trade Echo (199), Volland (150 a 400), MenthorQ Pro (349), FlashAlpha Growth (299) | El modelo de posicionamiento como producto central, intradía |
| Premium cuasi institucional | USD 700 a 1,500 | SqueezeMetrics (720), Heatseeker (699), Volland Live (1,000), FlashAlpha Alpha (1,499) | Histórico profundo, API, baja latencia |
| Institucional | USD 1,999 en adelante | SpotGamma Institutional (no verificado), Tier1Alpha directo (precio no público) | Datos crudos, soporte, compliance |

En negritas los operadores en español, para que se vea dónde caen: dos en la banda de overlay y dos en la de retail generalista. El tier Trader de USD 39 del plan de agosto queda entre GEXfocus (USD 30, con apps móviles y actualización cada 10 a 15 segundos) y GammaContext (USD 39 anualizado, con WebSocket sub-200 ms). No hay espacio de precio ahí.

### Los cinco operadores en español, con detalle

| Operador | Precio | Métricas | Latencia | Universo | Entrega |
|---|---|---|---|---|---|
| GEXfocus | USD 7 mensuales (cadena US diferida 15 min), USD 30 (flujo en vivo), USD 70 API | GEX, Put/Call Wall, NDF (Net Delta Flow), FEP (Flow Equilibrium Price), 0DTE, vanna, charm, heatmaps, replay | Plan de 30: cada 10 a 15 s, NDF cada 2 a 3 s | SPX, QQQ, SPY y ETFs US principales | WebApp, iOS, Android, API REST y WebSocket, TradingView, Discord, servidor MCP |
| GammaContext | PRO USD 49 (39 anual), ALGO USD 99 (79 anual) | Net DEX y GEX por strike, Long Wall, Zero Gamma, Short Fuel, convexidad, vanna, charm, IV skew, replay 30 días | WebSocket menor a 200 ms, tick a tick | NQ, ES, RTY, YM e índices | Web, plugin nativo NinjaTrader 8, export CSV |
| Tradeknowlogy GEX | USD 89 mensuales, USD 889 anuales | GEX, Gamma Flow, Volume, Delta, Acceleration, vanna, charm, Gamma Flip | Tiempo real, basado en volumen intradía | 12 símbolos: SPX, NDX, VIX, SPY, QQQ, DIA, GLD, /ES, /NQ | Web, alertas, contenido en YouTube en español |
| Gammetric | USD 29.95 (lanzamiento) | GEX tiempo real, GEX Levels diarios, Zero Gamma, Call/Put Walls, HVL | Chart en tiempo real, niveles al cierre | Solo ES y NQ | Web e indicador NinjaTrader |
| gammaibex (GEX MEFF) | Gratis | GEX, DEX, Call/Put Walls, Zero Gamma, con fórmula publicada | Diaria, al cierre | IBEX-35, Mini IBEX y acciones del Ibex | Dashboard web |

Dos lecturas. La primera: Tradeknowlogy critica explícitamente el interés abierto estático y construye sobre volumen intradía, que es la crítica correcta y la que más presiona a SpotGamma. La segunda: **ninguno de los cinco declara fuente de datos ni publica metodología auditable, y ninguno tiene densidad.** Ese es el hueco.

---

## 2. Las cuatro fisuras metodológicas del sector

Esto es lo que separa un producto defendible de un tablero bonito. Las cuatro están documentadas y ninguna está resuelta comercialmente.

### 2.1 El signo del gamma del dealer es un prior, no una medición

El paper fundacional de SqueezeMetrics (2016, revisado 2017) declara cuatro supuestos: toda opción involucra a un delta-hedger, los calls los venden los inversores y los compran los market makers, los puts los compran los inversores y los venden los market makers, y los MM cubren exactamente al delta. Los supuestos dos y tres son una convención de signo aplicada uniformemente a todo el interés abierto.

La evidencia contra es fuerte y viene de datos institucionales:

Gârleanu, Pedersen y Poteshman (RFS 2009) usan interés abierto de CBOE segregado por categoría de participante y documentan que los usuarios finales están **netos largos** en opciones sobre S&P 500 (demanda neta agregada aproximada de +103,260 contratos diarios). Si el cliente es neto largo en el complejo de índice, el dealer está estructuralmente **corto** gamma y el signo positivo sobre la pata de calls es incorrecto para SPX. En opciones sobre acciones individuales el mismo paper encuentra el signo invertido (demanda neta de −2,717 contratos), consistente con el prior ingenuo. Es decir: **el prior es aproximadamente correcto en single names y probablemente invertido en índice**, que es exactamente al revés de donde la industria lo aplica con más convicción.

Cboe, con datos etiquetados por participante, aporta el argumento cuantitativo: en un strike con 100,000 contratos negociados los market makers quedaron cortos alrededor de 3,000 contratos, el 3% del volumen bruto. El gamma neto de dealers en SPX 0DTE oscila entre USD 170 y 670 millones contra unos USD 400 mil millones de volumen diario de futuros del S&P, entre 0.04% y 0.17% de la liquidez. El GEX ingenuo imputa la totalidad del interés abierto a un lado: sobreestima la presión de cobertura en uno a dos órdenes de magnitud, y su signo lo determina el 97% que se cancela.

**Consecuencia práctica:** dos proveedores "midiendo GEX" pueden reportar signos opuestos el mismo día sin que ninguno tenga un error de programación.

### 2.2 Spot-shift contra agregación acumulada por strike

Dos métodos incompatibles para el gamma flip. El primero repricea la cadena completa sobre una malla de spots hipotéticos (típicamente ±20%) y resuelve el cruce por cero de la función continua: lo usan SpotGamma, SqueezeMetrics y ZeroGEX. El segundo suma gamma por interés abierto por strike y busca el umbral acumulado: lo usan Unusual Whales y Cheddar Flow.

El segundo está sesgado de forma documentada. Produce un flip que se queda pegado a un muro mientras ese muro esté en el snapshot, aunque el cero real esté varios puntos porcentuales más lejos. Además, en cadenas densas at-the-money (0DTE de SPX, QQQ), varios brackets adyacentes tienen magnitud casi igual y un tick de interés abierto hace que el nivel reportado se teletransporte cientos de puntos. Peor: puede reportar un flip por encima del spot mientras el gamma agregado en el spot es claramente positivo, lo que es una inconsistencia de régimen.

Esto explica por qué distintos productos publican flips distintos el mismo día. No es ruido, es metodología, y nadie la declara.

### 2.3 Inferencia contra etiquetado

Solo OptionsDepth afirma usar datos de Cboe etiquetados por participante, con la declaración textual de que su analítica no está inferida de spreads bid/ask ni de heurísticas de cinta. Todos los demás infieren.

Volland es el más explícito sobre su inferencia: clasifica orden por orden sobre OPRA usando precio ejecutado contra valor teórico Black-Scholes, órdenes circundantes y bid/ask, y reclama precisión superior al 90% contra el open-close de Cboe, 99% en 0DTE. Esa afirmación no es verificable externamente y hay que leerla contra la literatura.

Y la literatura es dura. Grauer, Schuster y Uhrig-Homburg (SSRN 4098475) establecen que el éxito de los algoritmos de clasificación de trades en opciones es considerablemente menor que en acciones, con causa principal identificada: los traders sofisticados ejecutan con órdenes límite, así que el iniciador no es identificable por posición respecto al mid. Sus reglas corregidas mejoran la precisión entre 6 y 47 puntos porcentuales según la estructura de fees del exchange. El impacto es material: en una estrategia long-short sobre desequilibrio de órdenes de opciones, el Sharpe pasa de 2.22 a 4.25 solo por cambiar la regla de clasificación.

**El error de clasificación no es ruido blanco.** Está correlacionado con el tipo de participante, y el peor clasificado es el institucional sofisticado, que es exactamente aquel cuyo posicionamiento importa.

Problemas adicionales que casi ninguna implementación trata: las patas de un spread imprimen por separado y clasificarlas independientemente sobreestima sistemáticamente el cambio de interés abierto (el flujo institucional es mayoritariamente spreads, y OPRA sí trae códigos de condición para identificar el paquete complejo); los rolls generan dos prints con exposición neta cero; el ejercicio temprano reduce interés abierto sin generar trade; y la cinta no distingue las cuatro combinaciones de apertura y cierre, de las cuales solo dos mueven el interés abierto.

### 2.4 Interés abierto de la noche anterior contra volumen intradía

El interés abierto autoritativo lo produce la OCC en el ciclo de compensación nocturno. No existe interés abierto intradía en ninguna fuente pública. Todo producto que anuncia "OI en tiempo real" está corriendo un modelo de inferencia con las barras de error del punto anterior.

Con 0DTE representando entre 50% y 60% del volumen de SPX (Cboe reporta cerca de 2 millones de contratos diarios en SPX 0DTE), un GEX basado en interés abierto de fin de día es ciego a la mayoría del gamma que estará vivo en la sesión. Esta es la crítica que más presiona a SpotGamma, cuyos niveles core se fijan pre-market con el interés abierto de la noche, y a SqueezeMetrics, que es EOD puro.

**Advertencia adicional que ya conoces y que hay que declarar en el producto:** el `oi_total` del día d es siempre el interés abierto del cierre de d menos uno. Max pain y GEX calculados sobre eso son correctos solo si el lector sabe de qué día son.

---

## 3. Qué necesitas de la fuente primaria, y qué cuesta

### 3.1 Qué entrega OPRA y qué no

De la especificación oficial OPRA Pillar Output:

| Mensaje | Contenido | Sirve para GEX |
|---|---|---|
| Open Interest (categoría d) | Open Interest Volume, entero sin signo | Sí, es el insumo base |
| End of Day Summary (categoría f) | Open, High, Low, Last, Net Change, Open Interest | Sí |
| Last Sale (categoría a) | Precio, tamaño, exchange, códigos de condición, mecanismo de ejecución | Parcial, **sin lado** |
| Quotes (categoría q) | NBBO y mejor bid/offer por exchange | Para greeks e IV |

**OPRA no entrega lado de la operación en ningún mensaje.** El campo Trade Identifier está marcado en la especificación como "FOR FUTURE USE. Filled with Hex 0x00". Tampoco entrega profundidad de libro (es un feed L1), ni opciones sobre futuros de índice (CME e ICE quedan fuera), ni interés abierto intradía.

Esa ausencia es estructural. Es la razón por la que existen los productos open-close de los exchanges y por la que cuestan lo que cuestan.

### 3.2 Cboe Open-Close Volume Summary

Es el dato que convierte una convención en una medición.

Contiene cuatro clases de participante (Customer, Professional Customer, Broker-Dealer, Market Maker) cruzadas con dos ejes ortogonales por trade, compra o venta y apertura o cierre, lo que da cuatro buckets por clase, más sub-buckets de tamaño para las dos categorías de cliente (menos de 100, 100 a 199, más de 199 contratos). Granularidad por serie: strike, vencimiento y tipo. Exchanges BZX, C1, C2 y EDGX, con C1 incluyendo sesión global desde el 11 de diciembre de 2023 e historia EOD desde 2005.

Entrega EOD después de medianoche ET, incluyendo OHLC, volumen e interés abierto. Intradía en snapshots de 10 minutos y de 1 minuto, **sin el campo de interés abierto**. SFTP o Snowflake.

La reconstrucción de posición por contrato para una clase de participante c es:

```
ΔNet_c(t) = (BO_c − SC_c) − (SO_c − BC_c) = BO_c − SO_c + BC_c − SC_c
Net_c(t)  = Net_c(t0) + Σ ΔNet_c(s)
```

Con dos restricciones de consistencia que la mayoría de implementaciones ignora: la identidad de suma cero (Σ_c Net_c = 0 para todo contrato, lo que permite despejar el lado del dealer por residuo, más robusto que medirlo directamente) y el anclaje al interés abierto de la OCC (Σ_c max(Net_c, 0) = OI, reconciliado semanalmente para evitar deriva). El vencimiento es el mejor ancla disponible: en T la posición va a cero por construcción.

**Sesgo de cobertura crítico:** para SPX y SPXW, producto propietario de Cboe, el open-close cubre cerca del 100% del volumen. Para opciones multi-listadas sobre acciones y ETFs, Cboe es una fracción del consolidado, y esa fracción no es aleatoria (varía con la estructura de fees y con el tipo de participante). Extrapolar el mix de Cboe al consolidado introduce un sesgo de selección no cuantificado. Esto explica por qué OptionsDepth se restringe deliberadamente a SPX y VIX: es coherente, no es una limitación de producto.

**Precios** (Cboe no los publica en DataShop; están en el fee schedule presentado a la SEC):

| Concepto | USD mensuales |
|---|---|
| Open-Close End-of-Day | 600 |
| Open-Close Intraday | 1,000 |
| **Distribución externa de datos derivados de Open-Close** | **5,000** |
| Descuento académico | 1,500 anuales |

Texto literal del fee schedule, decisivo para tu caso: "The fee for external distribution of Derived Data from Open-Close Data is in addition to fees for the End-of-Day product or the Intraday product, or both, as applicable."

### 3.3 Nasdaq, renombrado Trade Outline en 2024

| Producto | EOD | Intradía | Distribución externa ilimitada de derivados |
|---|---|---|---|
| ISE Trade Outline | 850 | 2,500 | **4,500** |
| GEMX Trade Outline | 575 | 1,500 | **3,000** |
| PHLX (PHOTO) | 850 | 3,000 | **5,000** |
| Nasdaq (NOTO) | 575 | 2,000 | **4,000** |

Todo en USD mensuales. Entre Cboe (4 exchanges) y Nasdaq (6) se cubren 10 de aproximadamente 17 bolsas de opciones de EE.UU. NYSE tiene su propio Open-Close Volume Summary, precio no verificado.

### 3.4 Proveedores comerciales y derechos de redistribución

| Proveedor | Precio USD mensual | Redistribuir a suscriptores de pago |
|---|---|---|
| Intrinio | Individual 150, **Startup 333** (6 meses, luego 666, luego 999), Enterprise 1,250+ | Individual no. **Startup sí, con "Commercial Use and Display Rights" explícitos.** La opción comercial más barata y clara encontrada |
| Databento | Standard 199, Plus 1,750, Unlimited 4,500, más uso por GB | Parcialmente. Texto literal: "Most of our datasets can be redistributed internally or externally **after 24 hours**". Encaja con un producto T+1 |
| Massive (ex Polygon) | Starter 29 (15 min, con OI, greeks e IV), Developer 79, Advanced 199 | No en planes personales, marcados "non-pros only". Business pricing existe, precio no publicado |
| ThetaData | Value 40, Standard 80, Pro 160 | No. Textual: "Individual Personal use only, no redistribution or business use". Página comercial devuelve 404 |
| ORATS | Delayed API 99, Live API 199, Live Intraday 399 | No confirmado, la página no contiene términos de redistribución |
| FMP | Starter 22, Premium 59, Ultimate 149 | No. Requiere "Data Display and Licensing Agreement" aparte. Además, el comparativo de planes no menciona datos de opciones, OI ni greeks |
| dxFeed | No publicado | No confirmado |

### 3.5 TastyTrade: el bloqueo es contractual y es definitivo

Del API Terms of Service de tastytrade:

- Cláusula 8(4): "you will not copy, distribute, show, make available or publish any Data made available to you via the API Connection to any third party for whatever reason."
- Cláusula 8(6): prohíbe re-transmitir, suministrar, mostrar o hacer disponible cualquier Data, incluyendo cualquier subconjunto, a un tercero de cualquier manera.
- Cláusula 8(10): el output procesado sigue sujeto a las restricciones si el Data transmitido "can be readily identified, recalculated or re-engineered" del resultado, o si el resultado puede usarse como sustituto del Data.
- Cláusula 8(3): limita el uso a trading y watchlists, y dice expresamente que el acuerdo "does not permit for subscribing to large cross-sections of the market for data collection purposes".

Una serie de GEX por strike publicada a suscriptores es re-ingenierizable hacia el interés abierto por strike, así que la cláusula 8(10) aplica. Y `capture_raw_chains.py` con 32 subyacentes por 7 vencimientos es literalmente lo que prohíbe la 8(3).

**La ruta TastyTrade sirve para investigación y para tu herramienta de un solo operador. No puede alimentar el producto de pago.** Esto convierte la prueba pendiente del evento `Summary` en una solución técnica a un problema que es contractual. Vale la pena correrla igual, porque desbloquea las siete métricas derivadas para tu uso interno y para validar el motor, pero no cambia la compuerta comercial.

### 3.6 La cuota de redistribuidor de OPRA: la contradicción resuelta

La contradicción documentada en el RFQ de agosto queda resuelta contra Theta Data. El texto literal del OPRA Fee Schedule define el alcance de la cuota de redistribuidor de USD 1,500 mensuales como aplicable al vendor que redistribuye datos de OPRA a cualquier persona "whether on a current or delayed basis, except that this fee does not apply to a Vendor whose redistribution of OPRA Data is limited solely to 'historical' OPRA Data".

La frase "whether on a current or delayed basis" es explícita. Los datos diferidos 15 minutos **no** están exentos. La única excepción es la redistribución exclusivamente histórica.

El error de Theta Data viene de fusionar dos familias de cuotas distintas:

| Cuota | ¿Aplica a diferido 15 min? |
|---|---|
| Por usuario (profesional 31.50, no profesional 1.25) | **No**, son por display de datos current |
| Redistribuidor (1,500 mensuales) | **Sí**, texto expreso "current or delayed" |

Para 200 usuarios no profesionales: 200 × 1.25 = USD 250 mensuales. Trivial. **El costo real es la cuota fija, no el volumen de usuarios.** Lo que significa que el costo por usuario cae de forma brutal con la escala, y que a 20 usuarios el producto bajo licencia propia es económicamente absurdo.

Nota de secuencia, al 1 de septiembre. La fase actual es investigación y uso personal de los datos, sin ninguna plaza vendida. Bajo ese alcance ninguna compuerta de licencia de esta sección muerde todavía: se difieren, no se resuelven. Muerden el día que exista un suscriptor de pago viendo una gráfica, y ese día llega sin aviso, así que las respuestas conviene tenerlas antes y no después.

**Dos preguntas abiertas de altísimo apalancamiento**, ninguna resuelta en fuente primaria:

1. OPRA no define "historical" en el fee schedule ni en las FAQs. Un producto estrictamente T+1 (GEX de ayer, publicado hoy, sobre interés abierto de ayer, que es de todos modos la latencia real del dato) podría caer en esa excepción. Si la respuesta es afirmativa, eliminas USD 18,000 anuales de la estructura de costos.

   **Decisión tomada: T+1, y T+2 si hace falta, es el supuesto de operación del producto.** Esto no es una concesión, es la elección correcta por tres razones convergentes. El interés abierto de la OCC es T-1 de todos modos, así que T+1 no pierde información real. La excepción "historical" de OPRA solo puede alcanzar a un producto que no publique nada current. Y la cláusula de Databento que permite redistribución externa después de 24 horas está literalmente escrita para esta forma de producto. Las tres piezas apuntan al mismo diseño. Fijar T+1 desde ahora hace que la pregunta a OPRA valga más, no menos, porque la respuesta afirmativa se vuelve directamente accionable.

   Prioridad declarada del proyecto, en orden: primero uso viable para la operación propia de trading, después publicación del dato como gráfica bajo suscripción, y solo cuando eso sea sostenible, integración con un graficador. ATAS está en conversación por un partnership de creación de contenido, todavía en definición. Como partnership de contenido no toca la licencia de datos y no lo bloquea nada de este documento. La bandera aparece solo si más adelante se convierte en distribución de indicadores, porque entonces sí redistribuiría dato derivado a los usuarios de ATAS. Vale la pena cultivarlo: las diez integraciones nativas de plataforma son la mayor fortaleza de MenthorQ, y ATAS está en esa lista.
2. El fee schedule tampoco define "Derived Data". Lo que sí define es Non-Display Use, y su definición **excluye expresamente** el procesamiento que sirve de soporte al display o a la redistribución del recipient. Un motor de GEX cuyo único producto es un gráfico mostrado al suscriptor cae, defendiblemente, en esa exclusión. Marketdata.app sostiene la lectura contraria (que calcular greeks en backend dispara USD 2,000 mensuales por categoría), pero esa es la lectura de un tercero, no de OPRA.

Ambas deben preguntarse por escrito. Son las dos preguntas de mayor retorno de todo el proyecto.

**Contraste útil:** donde OPRA calla, Cboe y Nasdaq hablan con toda claridad, y ambos crearon líneas tarifarias específicas y caras para distribución externa de datos derivados. Esa asimetría sugiere que los exchanges consideran que el derecho no viene incluido. Es prudente asumir lo mismo respecto de OPRA hasta tener respuesta escrita.

---

## 4. La aritmética que decide

Supuestos actualizados al 1 de septiembre. La cuenta de Stripe es de Estados Unidos, así que la comisión de referencia es 2.9% más USD 0.30: un tier Trader de USD 39 neto queda en USD 37.57, y un Pro de USD 89 en USD 86.12. La diferencia contra el supuesto anterior de cuenta mexicana es marginal y no mueve ninguna conclusión.

Dos hechos del estado actual cambian la lectura de esta sección. **No se ha vendido ninguna plaza de fundador**, así que no hay base instalada que migrar y la libertad de reposicionamiento es total. Y **el cobro corre hoy por Skool, no por Stripe**, lo que probablemente vuelve innecesarios los Hitos 0 y 4 del plan de agosto: enlace de pago, Checkout, webhook con firma e idempotencia, portal de cliente y los cuatro estados de autorización. Eso son los días 7 a 9 del plan. Queda por verificar si Skool puede otorgar y revocar el acceso a la aplicación, que es la única función que Stripe cumplía y que Skool tendría que cubrir. Infraestructura (hosting FastAPI y Streamlit, base de datos, API de Anthropic cacheada) estimada en USD 70 mensuales.

### Escenario A: posicionamiento real de dealer, licencia propia

| Concepto | USD mensuales |
|---|---|
| OPRA Redistributor | 1,500 |
| OPRA no profesional × 200 | 250 |
| Cboe Open-Close EOD | 600 |
| Cboe derivados, distribución externa | 5,000 |
| Nasdaq ISE Trade Outline EOD | 850 |
| Nasdaq ISE derivados, distribución externa | 4,500 |
| Infraestructura | 70 |
| **Total** | **12,770** |

Equilibrio: **340 suscriptores Trader**, o 148 suscriptores Pro. Con cobertura parcial del mercado (10 de 17 bolsas) y sin margen. No cierra en el horizonte de tu plan.

### Escenario B: GEX ingenuo sobre interés abierto, vía Intrinio Startup

| Fase | Datos | Infra | Total | Equilibrio Trader |
|---|---|---|---|---|
| Meses 1 a 6 | 333 | 70 | 403 | **11 suscriptores** |
| Meses 7 a 12 | 666 | 70 | 736 | **20 suscriptores** |
| Estado estable | 999 | 70 | 1,069 | **29 suscriptores** |
| Si OPRA cobra redistribuidor | 999 + 1,500 | 70 | 2,569 | **69 suscriptores** |

Esta es la única estructura viable en el rango de 20 a 200 usuarios. Su viabilidad depende por completo de las dos preguntas abiertas a OPRA.

### Escenario C: T+1 puro sobre Databento

USD 199 mensuales del plan Standard más licencias pasadas a costo, apoyándose en la cláusula de redistribución externa después de 24 horas. Atractivo porque T+1 es de todos modos la latencia real del interés abierto. Requiere confirmar con Databento que OPRA.PILLAR está entre esos datasets, lo cual no está verificado.

### Lectura

El Escenario B con Intrinio Startup te da doce meses de pista con un equilibrio entre 11 y 20 suscriptores, que es alcanzable con tu pool actual de 12 a 20 personas de la llamada diaria. El Escenario A es una decisión de fase 2 con umbral de activación explícito: **no comprar licencias de open-close por debajo de 350 suscriptores.** Fijar ese número ahora evita que la decisión se tome por entusiasmo.

---

## 5. Dónde Prob-Edge ya tiene ventaja

Esto es lo que el estudio de mercado no anticipaba y que cambia la recomendación.

**Ninguno de los operadores relevados publica una densidad neutral al riesgo.** Publican niveles derivados de gamma. La densidad es un objeto distinto: es la distribución completa que el mercado está descontando, y de ella salen probabilidades condicionales, precio de cola, medidas de asimetría normalizada y comparación contra lognormal. Tú ya la tienes construida y diagnosticada.

Más aún: **tres de las decisiones de implementación que la sección técnica identifica como dominantes ya están resueltas en tu código.**

| Decisión dominante en GEX | Estado en Prob-Edge |
|---|---|
| Forward y descuento implícitos por paridad put-call, por vencimiento, en lugar de (r, q) exógenos | **Ya implementado** en `rnd_forward.py`, por cruce call-put interpolado localmente. Identificado en la literatura como el cambio de implementación de mayor retorno para GEX de índice |
| Ajuste de sonrisa en lugar de interpolación punto a punto | **Ya implementado**, polinomio grado 4 en log-moneyness por mínimos cuadrados ponderados por 1/(1+spread relativo), sobre OTM. Con R² de 0.991 a 0.999 |
| Higiene de cadena antes de agregar | Parcialmente. Filtras por spread relativo vía ponderación. Faltan los gates duros: bid > 0, cota sobre |d1|, piso de vega |
| Derivada de la sonrisa ∂σ/∂k | **Disponible analíticamente** por ser un polinomio. Es el insumo del gamma efectivo con corrección de vanna, que nadie en el sector aplica |

Esa última línea es la más importante del documento. El gamma efectivo bajo régimen no sticky-strike es:

```
Γ_eff = Γ_BS + 2·Vanna·(∂σ/∂S) + Vomma·(∂σ/∂S)² + Vega·(∂²σ/∂S²)
```

Con el skew de SPX (del orden de −1.5 a −3 puntos de vol por 1% de moneyness), el término de vanna **no es una corrección de segundo orden: puede cambiar el signo del agregado**. Es la objeción técnica más defendible contra los niveles de zero-gamma publicados por todo el sector. Y tú tienes la derivada de la sonrisa en forma cerrada porque ajustas un polinomio en vez de interpolar.

Nadie más lo hace. No porque no sepan, sino porque su pipeline parte de greeks de proveedor sobre una superficie que no controlan.

---

## 6. La posición recomendada

**No competir en GEX. Competir en la unión de densidad y GEX, con metodología publicada.**

Tres capas, en este orden:

**Capa 1, la densidad (ya existe).** Es el activo diferenciado. Lo que el mercado descuenta como probabilidad, con diagnósticos publicados en el propio producto: integral, razón de desviación contra lognormal, curtosis, R² de la sonrisa, masa capturada. Ningún competidor publica esto.

**Capa 2, GEX auditable (por construir).** No "GEX", sino "GEX reproducible": fórmula publicada, convención de signo declarada y justificada, régimen de sonrisa declarado, reloj de T declarado, gates de rechazo publicados, y devolución de nulo con advertencia cuando la cadena está degradada en lugar de fabricar un nivel obsoleto. El único operador que se acerca a esto es ZeroGEX, y solo publica sus gates de rechazo. La crítica académica de fondo al sector es la irreproducibilidad. Tú tienes doctorado y ya escribiste `metodologia.md`: publicar la metodología es gratis y es una barrera que un vendor con marca no puede cruzar sin desnudar su caja negra.

**Capa 3, la lectura (ya la vendes).** La llamada diaria y el marco de interpretación. Es lo que ningún competidor puede replicar sin una persona con doctorado apareciendo todos los días. Esto no cambia respecto del plan de agosto.

El eje de venta: **densidad y flujo en la misma pantalla.** Dónde el mercado pone probabilidad, y dónde está el gamma que va a defender o romper esos niveles. La densidad dice qué es probable; el GEX dice quién tiene que operar si el precio llega ahí. Ese cruce no lo publica nadie.

Nota de honestidad intelectual que conviene incorporar al producto: la propia SqueezeMetrics reconoce en *The Implied Order Book* que cuando GEX está cerca de cero coexisten regímenes de alta y baja volatilidad, y que hace falta el complemento de vanna. La densidad es un complemento más informativo que VEX para ese mismo problema.

---

## 7. Requerimientos técnicos: checklist de implementación defendible

Ordenado por impacto sobre el resultado.

| Decisión | Elección defendible | Impacto | Estado en Prob-Edge |
|---|---|---|---|
| Signo del dealer | Cboe open-close por participante en SPX y VIX. En el resto, prior explícito, documentado y con el signo justificado por clase de subyacente (índice contra single name, que van en direcciones opuestas) | **Dominante** | No existe. Requiere decisión de licencia |
| Forward y descuento | Implícito por paridad put-call, por vencimiento | Alto | **Hecho** |
| Reloj de T | Tiempo de negocio con ponderación intradía (la sesión nocturna vale 0.10 a 0.20 de un día). Calendario/365 es indefendible en 0DTE, cambia el gamma ATM en más de 30% | Alto en 0DTE | Por hacer |
| Superficie de IV | SVI o eSSVI libre de arbitraje con condición de Durrleman (mariposa) y monotonía de varianza total en T (calendario), más gates de higiene: bid > 0, spread/mid acotado, cota sobre |d1|, piso de vega | Alto | Polinomio grado 4 hoy, funciona; SVI da no arbitraje y ∂²σ/∂k² |
| Gamma | Γ_eff con corrección de vanna, régimen de sonrisa documentado | Alto en índice | Insumo disponible, no aplicado |
| 0DTE | Abandonar la derivada local. Usar HedgeFlow integrado en banda: Σ χ·OI·M·[Δ(S(1+x)) − Δ(S)]·S(1+x). Finito y bien condicionado en T→0, elimina la dependencia del clip arbitrario de T | **Dominante en la última hora** | Por hacer |
| Zero-gamma | Repricear la cadena completa sobre una banda de spots hipotéticos, resolver el cruce de la función continua, verificar consistencia de régimen contra el gamma en el spot | Alto | Por hacer |
| Agregación en T | Reportar la estructura temporal G(T). No colapsar, o truncar en T ≤ 30 días y reportar el resto aparte | Medio | Por hacer |
| Cross-product | Netear SPX, SPXW, XSP, SPY y ES en unidades de índice. Un GEX de SPY aislado es incompleto por construcción: todos cubren contra el mismo pool de futuros | Medio-alto | Por hacer |
| Interés abierto | Anclar al de la OCC, reconciliar en cada vencimiento, **no fingir OI intradía**. Declarar el desfase T-1 en el producto | Alto | Bloqueado por la ruta de datos |
| Americanas (single names) | Binomial con dividendos discretos más borrow. Gamma BS europeo sobre puts ITM americanos es materialmente incorrecto, y en nombres con borrow caro es justo donde se acumula el gamma "negativo" del GEX ingenuo | Alto en single names | Por hacer |
| Doble contabilización | Eliminar OI de boxes, conversiones y reversals (delta y gamma cero por construcción), dividend plays, y tratar como caso especial las posiciones estructurales conocidas (el collar trimestral tipo JPM, ~40k contratos SPX, no se cubre de forma ingenua) | Medio | Por hacer |
| Unidades | Declarar cuál de las tres convenciones se usa. Entre "USD por 1%" y "USD notional por punto" hay un factor de S/100, que en SPX a 6,500 son 65× | Alto para comparabilidad | Por hacer |

**Sobre cómputo:** no es el cuello de botella y no hay que diseñar la arquitectura alrededor de él. El gamma BS es cerrado; el costo está en el solve de IV, del orden de 1 a 3 µs por contrato en un hilo. Un millón de contratos son 1 a 3 segundos en un hilo, menos de 100 ms en 32 núcleos. Con una cadena de índice aislada (SPX y SPXW son 10 a 20 mil series vivas), recalcular la superficie completa cada segundo es un no-problema. El costo real está en la ingesta y normalización de OPRA, en la calidad de la superficie, y en la conciliación del interés abierto.

**Sobre greeks de proveedor contra recalcular:** recalcular, pero reconciliar contra los del proveedor como control de calidad. Los greeks de proveedor se anulan o quedan nulos cuando la opción viola cotas de no arbitraje o el solve de IV falla, y esos huecos están concentrados en las alas profundas y cerca del vencimiento, que es exactamente donde vive el interés abierto grande y barato. Es un sesgo silencioso en la suma ponderada por OI, no ruido.

---

## 8. Qué hay que profundizar

Agenda de investigación, ordenada por dependencia.

**Bloque 1, licencias (bloquea todo lo demás).**
Las dos preguntas escritas a OPRA sobre "historical" y sobre si un agregado de GEX constituye Non-Display Use. Confirmación con Databento de si OPRA.PILLAR está entre los datasets redistribuibles a 24 horas. Confirmación con Intrinio de que el tier Startup cubre display de output derivado de opciones a suscriptores finales, con el detalle de qué campos de opciones incluye realmente.

**Bloque 2, el signo (define si el producto mide algo).**
Decidir y documentar la convención por clase de subyacente. La evidencia de Gârleanu-Pedersen-Poteshman sugiere signos opuestos en índice y en single names. Publicar esa decisión con su justificación es, en sí mismo, el diferenciador metodológico. Leer el paper de Chilingarian (SSRN 7131778, "The Sign of Dealer Gamma: A Reproducible, Auditable Framework"), que va exactamente en la dirección que te conviene ocupar y que no pude leer por bloqueo de SSRN.

**Bloque 3, validación (define si se puede vender sin mentir).**
Replicar Baltussen, Da, Lammers y Martens (JFE 2021) sobre tu propia serie cuando tengas historia: el momentum intradía condicional al signo del gamma, con β de 6.63 (t = 4.78) y R² fuera de muestra de 3.58% cuando el gamma neto es negativo, contra β de 0.82 no significativo cuando es positivo. Ese es el resultado más citado a favor del GEX, y usa el proxy ingenuo. Lo que demuestra es que incluso un proxy ruidoso conserva poder de condicionamiento, no que el proxy sea correcto. Es la afirmación honesta que puedes hacer.

**Bloque 4, la unión densidad y GEX (el producto propio).**
Nadie ha publicado esto, así que no hay literatura que copiar. Preguntas concretas: ¿el nivel de zero-gamma coincide con algún cuantil de la densidad de manera sistemática? ¿La masa de cola más allá de 2 sigmas contra lognormal (que ya calculas y que identificaste como el componente que ningún competidor de USD 25 mensuales puede publicar) tiene relación con la concentración de gamma en las alas? ¿El call wall coincide con el modo de la densidad, o con un punto de inflexión? Si hay una relación estable, es un paper y es el producto. Si no la hay, también es un hallazgo publicable y refuerza la posición de honestidad metodológica.

**Bloque 5, el defecto abierto de la densidad.**
La media de la densidad debería igualar al forward y no lo hace: error de 0.6 pb a 7 días creciendo a 27.9 pb a 98 días, siempre positivo en plazos largos, por asimetría en la masa fuera de la malla. Esto hay que cerrarlo antes de publicar la densidad como producto de pago, porque es el primer diagnóstico que un lector técnico va a revisar. La corrección de cola pendiente sigue pendiente.

---

## 9. Scorecard de decisiones

| Decisión | Horizonte | Impacto en caja | Prioridad |
|---|---|---|---|
| Reanudar la captura diaria. El repositorio no tiene commits desde el 17 de agosto y `data/raw/` solo contiene la corrida de prueba del 14 de agosto con SPY y QQQ. Dos semanas sin captura son dos semanas que se restan del IV Rank y de cualquier validación | 1 hora | Nulo hoy, decisivo a doce meses | ★★★★★ |
| Enviar las dos preguntas escritas a OPRA (definición de "historical", y si el agregado de GEX es Non-Display Use) | 2 horas | Hasta USD 18,000 anuales | ★★★★★ |
| Confirmar con Intrinio que el tier Startup cubre display de derivados de opciones a suscriptores finales, y qué campos de opciones incluye | 1 día de espera | Define si el Escenario B existe | ★★★★★ |
| Retirar TastyTrade de cualquier ruta comercial y declararlo por escrito en la documentación del proyecto. Mantenerlo solo para investigación | 30 min | Evita un riesgo legal de terminación de cuenta | ★★★★★ |
| No publicar el tier Trader a USD 39. El precio está entre GEXfocus (30, con apps móviles) y GammaContext (39 anualizado, con WebSocket). Reposicionar sobre la densidad antes de fijar precio | 1 día | Determina todo el modelo | ★★★★★ |
| Archivar a diario el CSV de investigación de TastyTrade. La ventana es móvil de doce meses: mañana se cae el día más viejo. Doce meses de IV de vencimiento constante sobre 104 símbolos, por una línea de cron. Ver Anexo A.6 | 20 min | Nulo hoy, es el activo histórico más barato del proyecto | ★★★★★ |
| Recalcular el ranking con IV Rank, IV Percentile y prima de riesgo de varianza, ya calculables con ese archivo. Deroga la nota de "agosto de 2027" y desbloquea el término que debía dominar un ranking de venta de prima. Ver Anexo A.4 | 1 día | Convierte el ranking provisional en publicable, para los 16 símbolos cubiertos | ★★★★★ |
| Conectar FMP `historical-price-eod` como fuente de RV20 para los 32 símbolos. Verificado el 1 de septiembre que cubre los 16 ausentes, incluidos IWM y COIN. Desbloquea el VRP sobre el universo completo sin comprar nada. Ver Anexo A.8 | Medio día | Convierte el ranking provisional en completo | ★★★★☆ |
| Verificar si Skool puede otorgar y revocar acceso a la aplicación. Si puede, los Hitos 0 y 4 del plan de agosto se eliminan y con ellos los días 7 a 9 | 1 hora | Ahorra tres días de desarrollo | ★★★☆☆ |
| Probar el evento `Summary` de dxFeed con mercado abierto. Desbloquea siete de diez métricas derivadas para uso interno y permite validar el motor de GEX contra datos reales antes de comprar licencia | 30 min con mercado abierto | Nulo directo, alto como validación | ★★★★☆ |
| Fijar por escrito el umbral de activación del Escenario A en 350 suscriptores, antes de que la decisión se tome por entusiasmo | 15 min | Evita un compromiso de USD 153,000 anuales prematuro | ★★★★☆ |
| Corregir la cola de la densidad (el error de media contra forward de hasta 27.9 pb) | 1 a 2 días | Requisito para publicar la densidad como producto | ★★★★☆ |
| Migrar la sonrisa de polinomio grado 4 a SVI o eSSVI con condición de Durrleman y monotonía de varianza total | 2 a 3 días | Habilita Γ_eff y VEX consistentes, y no arbitraje | ★★★☆☆ |
| Implementar Γ_eff con corrección de vanna. Es el diferenciador técnico que nadie aplica y para el que ya tienes el insumo | 1 día tras SVI | Diferenciación metodológica pura | ★★★☆☆ |
| Implementar HedgeFlow integrado en banda para el tramo 0DTE, en lugar de gamma puntual con clip de T | 1 día | Necesario si el producto habla de 0DTE | ★★★☆☆ |
| Agregar `websockets` a `requirements.txt` (está en el venv en 16.0, no declarado, y toda la ruta viva depende de él) | 2 min | Deuda pendiente desde el 16 de agosto | ★★☆☆☆ |

---

## 10. Banderas

**Regulatoria, sin resolver desde agosto.** Publicar niveles de GEX etiquetados como soporte y resistencia a suscriptores de pago está más cerca de la asesoría que publicar una densidad, no más lejos. La bandera planteada en las decisiones del reporte semanal (frontera entre contenido y asesoría, CNBV y del lado estadounidense) se agrava, no se alivia, con el movimiento hacia GEX. Tienes AMIB Figura 3 y conoces el terreno. Queda señalado otra vez, y ahora con más peso.

**Certificación de suscriptores.** La distinción profesional y no profesional de OPRA es una obligación auditable, no una casilla. La definición es el individuo que usa los datos solo para su actividad de inversión personal y de su familia inmediata, sin actividad comercial y sin ser profesional de valores. Instrumentar la recolección y conservación de esa certificación desde el primer suscriptor es mucho más barato que hacerlo retroactivamente.

**Riesgo de dilución.** Prob-Edge tiene hoy una cosa que hace bien y que nadie más hace. Añadir GEX sin resolver la licencia y sin la corrección de cola de la densidad convierte un producto con un diferenciador en un producto con dos funcionalidades a medias, en un mercado donde cuarenta competidores hacen una de ellas mejor y más barato.

**Sesgo de las fuentes de crítica.** No fue posible acceder a Reddit ni a Trustpilot (bloqueo 403 en ambos). La mayor parte de la crítica disponible sobre estos operadores en la web abierta está escrita por vendors competidores, y debe descontarse en consecuencia. Esto es la limitación principal del relevamiento competitivo.

---

## 11. Lo que no pude confirmar

| Punto | Motivo |
|---|---|
| Precios de GEXBot, Tradytics, ORATS, OptionCharts, CrossVol, ZeroGEX Basic y Pro, y del tier Options Plus de BlackBoxStocks | SPA sin renderizado, 404, o bloqueo por robots.txt |
| Vigencia del pricing de Volland | Única fuente pública: User Guide PDF de junio de 2024. Las páginas /pricing y /plans devuelven 404 |
| Tiers Standard, Pro e Institucional de SpotGamma citados por terceros | No aparecen en spotgamma.com/pricing |
| Fuente de datos de Unusual Whales, MenthorQ, GEXBot, Tier1Alpha, Cheddar Flow, BlackBoxStocks, Tradytics | No declarada |
| Precio comercial de ThetaData | Página /commercial devuelve 404 |
| Si OPRA.PILLAR está entre los datasets redistribuibles a 24 horas de Databento | No verificado |
| Términos de redistribución de ORATS | Ausentes de la página de producto |
| Cláusulas de Tradier, Alpaca e IBKR | No leídas. El patrón de la industria es uniforme, así que asumir prohibido salvo confirmación escrita |
| Precio del Open-Close Volume Summary de NYSE | No investigado |
| Definición de "historical" en el fee schedule de OPRA | No existe en el documento ni en las FAQs |
| Si un agregado de GEX constituye Non-Display Use bajo OPRA | No resuelto en fuente primaria, solo interpretación de terceros |
| Abstract del paper de Chilingarian sobre el signo del gamma del dealer | SSRN devolvió HTTP 429 |
| Reseñas independientes en Reddit y Trustpilot | Bloqueo 403 |

---

## Anexo A. El conjunto de investigación interna: qué sirve y qué no

Analicé el CSV de investigación interna descargado el 1 de septiembre de 2026, 1.38 MB. Es un conjunto de uso personal y de investigación, no una fuente contratada, y por eso no se identifica su origen en este documento. Fuera de este anexo no se cita.

### A.1 Qué contiene

| Atributo | Valor |
|---|---|
| Filas | 25,520 |
| Columnas | `time`, `Symbol`, `open`, `high`, `low`, `close`, `impVolatility` |
| Rango | 2025-09-02 a 2026-08-31 |
| Días hábiles | 251, sin un solo hueco de calendario, solo lunes a viernes |
| Símbolos | 104 |
| Universo | Nasdaq-100 más SPY y QQQ |

El último día es el 31 de agosto, es decir ayer. La actualización diaria está confirmada por observación directa.

### A.2 Calidad del dato

Está limpio. Los números:

| Prueba | Resultado |
|---|---|
| Huecos de calendario mayores a 4 días naturales | 0 |
| Violaciones `high < max(open, close)` | 0 |
| Violaciones `high < low` | 0 |
| Violaciones `low > min(open, close)` | 2, inmateriales |
| Cierres idénticos al día previo (proxy de dato rancio) | 53 de 25,520, 0.21% |
| IV idéntica al día previo | 71 de 25,520, 0.28% |
| Nulos en OHLC | 24 |
| Nulos en `impVolatility` | 18 |
| AR(1) medio de la IV en el universo | 0.918 |
| Saltos mayores a 3 sigma en la IV, fracción media | 1.85% |

Dos observaciones sobre los nulos. **Los 24 nulos de OHLC caen todos en una sola fecha, el 19 de marzo de 2026**, sobre diez símbolos, y afectan `open`, `high` y `low` pero no `close`. Es un fallo de ingesta de un día que nunca se corrigió. La conclusión operativa importa más que el defecto: **el proveedor no repara la historia de forma retroactiva.** Lo que captures es lo que tendrás.

Tres símbolos tienen historia parcial por ser altas recientes al índice: HONA (54 filas desde el 15 de junio), SPCX (55 desde el 12 de junio) y CSX (60 desde el 5 de junio). Excluirlos de cualquier estadística de ventana anual hasta que acumulen 252 sesiones.

### A.3 Qué es `impVolatility`

Es una volatilidad implícita del subyacente, un número por símbolo por día. Tres pruebas convergen en que es una medida de vencimiento constante cercana a 30 días, no la IV del vencimiento más próximo:

Los niveles son plausibles: SPY con mediana 17.1% (mínimo 9.4%, máximo 29.2%, último 14.8%), QQQ 23.4%, AAPL 27.6%, NVDA 43.7%.

No hay sierra de vencimiento. Medí el cambio medio de la IV de SPY en una ventana de siete días hábiles alrededor de cada tercer viernes durante doce ciclos. Los valores oscilan entre −0.011 y +0.005, todos dentro de una desviación diaria de la serie (0.019). Una IV del vencimiento más cercano mostraría una discontinuidad sistemática en el roll. No la hay.

La serie es suave y persistente: AR(1) de 0.82 en SPY y 0.92 en promedio del universo.

**Lo que no tiene: estructura temporal ni sesgo.** Es un escalar diario. Los dos primeros componentes de tu criterio de ranking, la pendiente `(iv30−iv90)/iv90` y el sesgo normalizado a 25 deltas, no se sirven desde aquí. Esos siguen saliendo de tus propias cadenas.

### A.4 Lo que desbloquea, y son tres cosas reales

**Primero, IV Rank e IV Percentile hoy, no en agosto de 2027.** Doscientos cincuenta y un días hábiles son cincuenta y dos semanas. Ese era el único renglón de la especificación del ranking bloqueado hasta agosto de 2027, y se colapsa doce meses. Verificado: 101 de 104 símbolos tienen ventana suficiente para calcular ambos hoy mismo.

**Segundo, la prima de riesgo de varianza, que es el término que debería dominar un ranking de venta de prima y estaba bloqueado por falta de historia de precios.** El componente `iv30 − RV20` es calculable de inmediato, y la verificación económica pasa:

| Estadístico sobre 101 símbolos | Valor |
|---|---|
| IV mediana | 0.420 |
| RV20 mediana | 0.351 |
| VRP mediana | +0.041 |
| Fracción de días con IV > RV20 | 71.1% |

Una prima mediana de 4.1 puntos de volatilidad y una IV por encima de la realizada siete de cada diez días es exactamente la forma que debe tener este objeto en un universo tecnológico. Y la cola negativa cae donde debe caer: los seis símbolos con VRP medio negativo son SNDK (−0.073), AMD (−0.039), TER (−0.035), NBIS (−0.027), INTC (−0.024) y ALAB (−0.020). Semiconductores y beta alta de inteligencia artificial, que son los nombres donde la realizada se come a la implícita. El signo tiene sentido económico, no solo estadístico.

Al cierre del 31 de agosto, el ranking por VRP encabeza con CTAS (+0.158), MPWR (+0.130), DASH (+0.114), BKR (+0.112) y ADBE (+0.110).

**Tercero, FMP sale de la ruta del reporte para los símbolos cubiertos.** `fetch_quote_history` era el único grupo de llamadas a FMP que toca el producto vendible, y alimenta las velas del cono. Este archivo lo reemplaza para su subconjunto y además resuelve el problema de historia hacia atrás que quedó abierto en la auditoría del día 0, sin depender de que el streamer token autorice el evento `Candle`.

### A.5 Lo que NO hace

**No aporta absolutamente nada al GEX.** No hay interés abierto, no hay volumen, no hay strikes, no hay cadena. El GEX necesita interés abierto por contrato. Este archivo no mueve esa aguja en ningún grado. Conviene decirlo sin matices para que no se confunda un avance real en el ranking con un avance en la línea de Gamma Exposure, que sigue exactamente donde estaba.

**Cubre 16 de tus 32 símbolos, el 50%, y solo 2 de 10 ETFs.**

| | Símbolos |
|---|---|
| Cubiertos | SPY, QQQ, AAPL, MSFT, NVDA, AMZN, GOOGL, META, TSLA, AMD, NFLX, AVGO, WMT, COST, INTC, MU |
| Ausentes | IWM, DIA, TLT, GLD, SLV, XLE, XLF, EEM, JPM, BAC, XOM, CVX, UNH, DIS, BA, COIN |

Es un archivo del Nasdaq-100. No hay financieras, energía, salud, small caps, bonos ni metales. Para el reporte semanal eso significa que la mitad del universo sigue sin la fuente de historia. **Para Smart-Beta, que es un marco factorial sectorial-relativo, el archivo es estructuralmente inservible como fuente única: no hay dispersión sectorial que medir.** Los 88 símbolos extra que trae son más Nasdaq, no más sectores.

### A.6 Dos advertencias, una urgente

**La ventana es móvil de doce meses. Si no lo archivas a diario, pierdes historia.** El 2 de septiembre de 2025 está exactamente 251 sesiones atrás del 31 de agosto de 2026. Mañana el día más viejo se cae del archivo. Archivarlo cuesta una línea de cron y es el activo histórico más barato de todo el proyecto: doce meses de IV de vencimiento constante sobre 104 símbolos, gratis, que en cualquier proveedor comercial cuestan dinero. Esto va antes que cualquier otra cosa de este anexo.

```bash
# ~/.config/systemd/user/tt-research-snapshot.service
[Unit]
Description=Snapshot diario del CSV de investigacion de TastyTrade
[Service]
Type=oneshot
WorkingDirectory=/home/leo/Documents/Claude/Projects/Prob-Edge
Environment=RESEARCH_CSV_URL=<pon la URL en el .env, nunca en el repo>
ExecStart=/bin/bash -c 'd=$(date +%%F); mkdir -p data/research; curl -sSfL --max-time 120 -o data/research/.tmp_$d.csv "$RESEARCH_CSV_URL" && gzip -f data/research/.tmp_$d.csv && mv data/research/.tmp_$d.csv.gz data/research/ohlc_$d.csv.gz'
```

```ini
# ~/.config/systemd/user/tt-research-snapshot.timer
[Unit]
Description=Snapshot diario del CSV de investigacion, dias habiles
[Timer]
OnCalendar=Mon..Fri 17:30
Persistent=true
[Install]
WantedBy=timers.target
```

Escritura atómica por `.tmp` y renombrado, misma disciplina que `capture_raw_chains.py`. Comprimido son del orden de 300 KB por día, unos 75 MB al año. Añadir `data/research/` al `.gitignore`.

**El alcance es uso personal e investigación.** No es una fuente contratada ni redistribuible, y no se menciona fuera de este anexo. Publicar un IV Rank o un ranking de VRP derivado de aquí a suscriptores de pago sería redistribución de dato derivado, porque el insumo es recalculable desde el output.

**Veredicto de uso:** entra en la operación propia de trading y en la investigación, que es la fase declarada del proyecto hoy. No entra al producto de pago. Y no hace falta que entre: la sección A.8 describe la ruta que sí es publicable, con FMP y con las cadenas propias, que cubre los 32 símbolos y no depende de este archivo.

### A.7 Salvedades menores para la implementación

Seis símbolos tienen correlación negativa entre IV y RV20: GOOG (−0.405), GOOGL (−0.400), AVGO (−0.395), DXCM (−0.395), AMGN (−0.383), IDXX (−0.354). GOOG y GOOGL coinciden a tres decimales entre sí, lo cual es una buena prueba de consistencia interna del archivo (misma empresa, dos clases de acción), así que esto es una propiedad de los nombres y del ciclo de reportes, no un defecto del dato. La consecuencia práctica es que un ranking de VRP sobre esos nombres es inestable y conviene marcarlo.

Los 18 nulos de IV afectan a CCEP, FER, HONA, NFLX, NXPI, SPCX, TRI y XEL. Propagar nulo, no interpolar.

### A.8 La ruta que sí es publicable: FMP más cadenas propias

Decisión tomada: se mantienen los 32 símbolos y se resuelve la fuente de los 16 ausentes. La respuesta es FMP, que ya está contratado. Verifiqué el 1 de septiembre que `historical-price-eod` responde con historia al día para los símbolos que faltaban, incluidos IWM y COIN.

| Insumo | Fuente | Cobertura | Estado |
|---|---|---|---|
| OHLC diario del subyacente, y de ahí RV20 | FMP `historical-price-eod` | 32 de 32 | Disponible hoy |
| IV30 | Cadenas propias capturadas | 32 de 32 | En cuanto la captura corra |
| VRP `iv30 menos RV20` | Las dos anteriores | 32 de 32 | En cuanto la captura corra |
| Pendiente de estructura temporal, sesgo a 25 deltas, precio de cola | Cadenas propias | 32 de 32 | Disponible hoy |
| IV Rank e IV Percentile | 52 semanas de IV30 | 16 hoy, 32 en un año | Parcial |

Dos consecuencias.

**La primera es buena: el ranking completo de venta de prima sobre los 32 símbolos deja de estar bloqueado en cuanto la captura reanude.** El término de VRP, que es el que debía dominarlo, sale de FMP más las cadenas propias, sin tocar el conjunto de investigación y sin comprar nada. Eso convierte el ranking provisional en un ranking con su componente principal puesto.

**La segunda acota el papel del conjunto de investigación.** Deja de ser fuente y pasa a ser dos cosas más útiles: el conjunto de validación contra el cual contrastar la IV30 calculada desde tus propias cadenas, que es una prueba cruzada que hoy no tienes, y la única vía para tener IV Rank sobre 16 símbolos antes de acumular 52 semanas propias. En ambos papeles el uso es interno y no hay problema de alcance.

El IV Rank de los otros 16 símbolos no tiene atajo. Se resuelve acumulando historia propia, que es exactamente por lo que reanudar la captura es la acción de cinco estrellas del scorecard.

**Salvedad sobre FMP.** El plan Premium cubre el uso personal y de investigación, que es la fase actual. La sección 2.2.2 de sus términos sigue prohibiendo el display multiusuario, así que FMP tampoco cruza la compuerta hacia el producto de pago. Para investigar no importa. Antes de cobrar, sí.


## 12. Fuentes

**Fuente primaria de datos y licencias**
- OPRA Pillar Output Specification: https://cdn.opraplan.com/documents/OPRA_Pillar_Output_Specification.pdf
- OPRA Fee Schedule: https://cdn.opraplan.com/documents/OPRA_Fee_Schedule.pdf
- OPRA Fee Schedule ante la SEC, File No. OPRA-2025-02: https://www.sec.gov/files/rules/sro/nms/2025/34-104267-ex1.pdf
- OPRA FAQs: https://www.opraplan.com/faqs
- Cboe DataShop, Open-Close Volume Summary: https://datashop.cboe.com/cboe-options-open-close-volume-summary
- Cboe fee schedule ante la SEC (2026): https://www.sec.gov/files/rules/sro/cboe/2026/34-104795-ex5.pdf
- Nasdaq Data News 2024-3, renombramiento Trade Outline: https://www.nasdaqtrader.com/TraderNews.aspx?id=DN2024-3
- Nasdaq US Options Price List 2025: https://www.nasdaqtrader.com/content/ProductsServices/PriceList/Nasdaq_US_Options_Price_List_2025.pdf
- Databento, What is OPRA: https://databento.com/microstructure/opra
- tastytrade API Terms of Service: https://assets.tastyworks.com/production/documents/USA/open_api_terms_and_conditions.pdf
- Intrinio Pricing: https://intrinio.com/pricing
- Databento Pricing: https://databento.com/pricing
- marketdata.app, OPRA Fees & Licensing Explained: https://www.marketdata.app/education/options/opra-fees/
- ThetaData, OPRA Fee Guide: https://www.thetadata.net/articles/2026-05-29-opra-fee-guide-for-options-market-data

**Literatura académica**
- Gârleanu, Pedersen, Poteshman (2009), "Demand-Based Option Pricing", RFS 22(10), 4259-4299: https://nbgarleanu.github.io/DBOP.pdf
- Ni, Pearson, Poteshman, White (2021), "Does Option Trading Have a Pervasive Impact on Underlying Stock Prices?", RFS 34(4), 1952-1986: https://academic.oup.com/rfs/article-abstract/34/4/1952/5873587
- Ni, Pearson, Poteshman (2005), "Stock price clustering on option expiration dates", JFE 78(1), 49-87
- Bollen, Whaley (2004), "Does Net Buying Pressure Affect the Shape of Implied Volatility Functions?", JF 59(2), 711-753
- Baltussen, Da, Lammers, Martens (2021), "Hedging demand and market intraday momentum", JFE 142(1), 377-403: https://academicweb.nd.edu/~zda/intramom.pdf
- Barbon, Buraschi (2020), "Gamma Fragility", SSRN 3725454
- Soebhag (2022), "Option Gamma and Stock Returns", SSRN 4256259
- Savickas, Wilson (2003), "On Inferring the Direction of Option Trades", JFQA 38(4), 881-902
- Grauer, Schuster, Uhrig-Homburg, "Option Trade Classification: Limits, Corrections, and Implications for Stock Returns", SSRN 4098475
- Chilingarian, "The Sign of Dealer Gamma: A Reproducible, Auditable Framework for Computing S&P 500 GEX", SSRN 7131778 (no accesible, HTTP 429)

**0DTE**
- Brogaard, Han, Won, "Does 0DTE Options Trading Increase Volatility?", SSRN 4426358
- Adams, Fontaine, Ornthanalai, "The Market for 0DTE: The Role of Liquidity Providers in Volatility Attenuation", SSRN 4881008
- Dim, Eraker, Vilkov, "0DTEs: Trading, Gamma Risk and Volatility Propagation", SSRN 4692190
- Cboe, "Evaluating the Market Impact of SPX 0DTE Options": https://www.cboe.com/insights/posts/volatility-insights-evaluating-the-market-impact-of-spx-0-dte-options/

**Documentos fundacionales de la industria**
- SqueezeMetrics, Gamma Exposure white paper: https://squeezemetrics.com/download/white_paper.pdf
- SqueezeMetrics, The Implied Order Book: https://squeezemetrics.com/download/The_Implied_Order_Book.pdf
- Volland, Impact of option dealer flows on equity returns: https://vol.land/VollandWhitePaper.pdf
- Volland, User Guide junio 2024: https://vol.land/VollandUserGuide_Jun24.pdf
- GEX Metrix, The Intraday Open Interest Problem: https://www.gexmetrix.com/blog/intraday-oi-problem
- FlashAlpha, The Gamma Flip Problem: https://flashalpha.com/articles/gamma-flip-methodology-stable-zero-gamma-level

**Competidores**
- SpotGamma: https://spotgamma.com/pricing/ y https://spotgamma.com/gamma-exposure-gex/
- Unusual Whales: https://unusualwhales.com/pricing
- MenthorQ: https://menthorq.com/pricing/
- Volland: https://vol.land/
- OptionsDepth: https://optionsdepth.com/pricing
- SqueezeMetrics: https://squeezemetrics.com/monitor/plans
- Tier1Alpha vía Hedgeye: https://accounts.hedgeye.com/products/market_situation_report/972!973
- GEXBoard: https://gexboard.com/pricing
- FlashAlpha: https://flashalpha.com/pricing
- Barchart SPX GEX: https://www.barchart.com/stocks/quotes/%24SPX/gamma-exposure
- GEXfocus: https://gexfocus.app/suscripciones
- GammaContext: https://gammacontext.com/
- Gammetric: https://gammetric.com/
- Tradeknowlogy GEX: https://gamma.tradeknowlogy.com/
- gammaibex (GEX MEFF): https://gammaibex.noquedaotraopcion.com/
- CrossVol: https://crossvol.com/en/gex/
