"""외부 호출 없는 보유 주식 정규화와 Decimal 진단 계산."""

from decimal import Decimal

from stock_agent.portfolio.schemas import Holding, SectorAssignments


def prepare_holdings(raw: dict, stocks: list[dict]) -> tuple[list[Holding], list[dict]]:
    """원본 Holdings와 종목 정보에서 원화 국내 STOCK을 추리고 중복 합산한다.

    반환은 계산용 Holding 목록과 제외 사유 목록이다. 외부 호출·저장 없음.
    필수 정보 누락·음수 또는 비유한 금액은 검증 오류로 중단하며 임의로 0을 채우지 않는다.
    """
    stock_map = {item["symbol"]: item for item in stocks}
    holdings: dict[str, Holding] = {}
    excluded = []
    for item in raw["items"]:
        symbol, name = item["symbol"], item["name"]
        info = stock_map.get(symbol)
        if item["marketCountry"] != "KR" or item["currency"] != "KRW":
            reason = "국내 원화 주식 외 자산"
        elif info is None:
            reason = "상품 유형 미확인"
        elif info["securityType"] != "STOCK":
            reason = "일반 주식 외 상품: " + info["securityType"]
        else:
            holding = Holding(
                symbol=symbol, name=name, amount=item["marketValue"]["amount"],
                purchase_amount=item["marketValue"]["purchaseAmount"],
            )
            if symbol in holdings:
                holdings[symbol].amount += holding.amount
                holdings[symbol].purchase_amount += holding.purchase_amount
            else:
                holdings[symbol] = holding
            continue
        excluded.append({"symbol": symbol, "name": name, "reason": reason})
    return list(holdings.values()), excluded


def calculate_diagnosis(holdings: list[Holding], assignments: SectorAssignments) -> dict:
    """검증된 보유 주식과 AI 업종으로 집중도·최대 종목 하락 영향을 계산한다.

    Decimal로 계산하고 JSON용 금액·비율 문자열을 반환한다. 부작용 없음.
    업종의 누락·중복·추가, 종목 중복 또는 총액 0은 ValueError로 거부한다.
    """
    symbols = {h.symbol for h in holdings}
    assigned = [item.symbol for item in assignments.items]
    if len(symbols) != len(holdings) or len(set(assigned)) != len(assigned) or set(assigned) != symbols:
        raise ValueError("업종 분류의 종목 누락·중복·추가를 확인하세요.")
    total = sum((h.amount for h in holdings), Decimal(0))
    total_purchase = sum((h.purchase_amount for h in holdings), Decimal(0))
    if total <= 0:
        raise ValueError("진단 가능한 원화 주식 평가금액이 없습니다.")
    sectors = {item.symbol: item for item in assignments.items}
    ordered = sorted(holdings, key=lambda h: (-h.amount, h.symbol))
    sector_amounts: dict[str, Decimal] = {}
    rows = []
    for holding in ordered:
        sector = sectors[holding.symbol]
        sector_amounts[sector.sector] = sector_amounts.get(sector.sector, Decimal(0)) + holding.amount
        rows.append({
            "symbol": holding.symbol, "name": holding.name, "amount": str(holding.amount),
            "purchase_amount": str(holding.purchase_amount),
            "profit_loss": str(holding.amount - holding.purchase_amount),
            "profit_loss_pct": (
                str((holding.amount - holding.purchase_amount) / holding.purchase_amount * 100)
                if holding.purchase_amount else None
            ),
            "weight_pct": str(holding.amount / total * 100),
            "sector": sector.sector, "reason": sector.reason,
        })
    shock = Decimal("-0.20")
    impact = ordered[0].amount * shock
    return {
        "currency": "KRW", "total_amount": str(total), "holdings": rows,
        "total_purchase_amount": str(total_purchase),
        "total_profit_loss": str(total - total_purchase),
        "total_profit_loss_pct": str((total - total_purchase) / total_purchase * 100) if total_purchase else None,
        "top_one_pct": rows[0]["weight_pct"],
        "top_three_pct": str(sum((h.amount for h in ordered[:3]), Decimal(0)) / total * 100),
        "sectors": [
            {"sector": sector, "amount": str(amount), "weight_pct": str(amount / total * 100)}
            for sector, amount in sorted(sector_amounts.items(), key=lambda pair: (-pair[1], pair[0]))
        ],
        "scenario": {
            "symbol": ordered[0].symbol, "name": ordered[0].name, "shock_pct": "-20",
            "impact_amount": str(impact), "impact_pct": str(impact / total * 100),
        },
    }
