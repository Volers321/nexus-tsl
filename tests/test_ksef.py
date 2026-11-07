import os
from xml.etree import ElementTree as ET

import pytest

from nexus_tsl.demo import SAMPLE_ORDER, sample_offers
from nexus_tsl.modules.ksef import NS, invoice_xml
from nexus_tsl.orchestrator import NexusPlatform

N = {"f": NS}


@pytest.fixture(scope="module")
def delivered():
    p = NexusPlatform()
    r = p.run(SAMPLE_ORDER, sample_offers())
    inv = p.store.get("invoice", r.shipment["documents"]["invoice"])
    return inv, p.get(r.shipment["id"])


def test_international_invoice_is_zero_kr(delivered):
    inv, s = delivered
    root = ET.fromstring(invoice_xml(inv, s).split("\n", 1)[1])
    assert root.find("f:Naglowek/f:KodFormularza", N).get("kodSystemowy") == "FA (3)"
    assert root.find("f:Fa/f:P_13_6_1", N).text == f"{inv['net']:.2f}"
    assert root.find("f:Fa/f:P_13_1", N) is None
    assert {w.text for w in root.findall("f:Fa/f:FaWiersz/f:P_12", N)} == {"0 KR"}
    assert root.find("f:Fa/f:DodatkowyOpis/f:Wartosc", N).text == s.reference


def test_domestic_invoice_has_23_vat(delivered):
    inv, s = delivered
    xml = invoice_xml(dict(inv, vat_rate=0.23), s, currency="PLN")
    root = ET.fromstring(xml.split("\n", 1)[1])
    net = float(root.find("f:Fa/f:P_13_1", N).text)
    assert float(root.find("f:Fa/f:P_14_1", N).text) == pytest.approx(net * 0.23, abs=0.01)
    assert root.find("f:Fa/f:KursWalutyZ", N) is None


@pytest.mark.skipif(not os.getenv("NEXUS_FA3_XSD"), reason="ustaw NEXUS_FA3_XSD=ścieżka/do/schemat.xsd")
def test_validates_against_official_xsd(delivered, tmp_path):
    lxml = pytest.importorskip("lxml.etree")
    # oficjalny schemat importuje typy z crd.gov.pl - zezwalamy na ich pobranie
    parser = lxml.XMLParser(no_network=False, resolve_entities=False)
    schema = lxml.XMLSchema(lxml.parse(os.environ["NEXUS_FA3_XSD"], parser))
    inv, s = delivered
    for variant in (inv, dict(inv, vat_rate=0.23)):
        doc = lxml.fromstring(invoice_xml(variant, s).encode())
        assert schema.validate(doc), schema.error_log
