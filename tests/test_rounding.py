from test_normalization import normalized
from goldenstock.normalization import conflicts


def test_source_rounding_boundaries_and_legacy():
    left=normalized(number_text='120',rounding='nearest_reported_digit')
    assert left['rounding_radius']=='500000'
    assert conflicts([left,normalized('b',number_text='120.49')])==[]
    assert conflicts([left,normalized('b',number_text='120.51')])[0]['severity']=='blocker'
    assert conflicts([normalized(number_text='120'),normalized('b',number_text='120.49')])
    assert conflicts([left,normalized('b',number_text='120.49',currency='RUB')])[0]['kind']=='context_mismatch'


def test_negative_percent_precision():
    left=normalized(number_text='(12.50%)',metric='roe',unit='percent',scale='units',currency='',rounding='nearest_reported_digit')
    assert left['rounding_radius']=='0.00005'
