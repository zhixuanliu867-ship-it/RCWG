"""Conservative admission bound from an explicitly frozen billing policy."""
from decimal import Decimal,InvalidOperation,ROUND_CEILING


def reservation_bound(binding,request,kind,measurement):
    price=binding['price_snapshot'] or {};policy=price.get('billing_policy',{})
    if policy.get('revision')!='FULL001_BILLING_BOUND_1' or policy.get('rates_are_upper_bounds') is not True:
        raise PermissionError('BILLING_BOUND_NOT_FROZEN')
    def amount(key):
        try:value=Decimal(str(price[key]))
        except (KeyError,ValueError,InvalidOperation):raise PermissionError('BILLING_RATE_UNKNOWN')
        if not value.is_finite() or value<0:raise PermissionError('BILLING_RATE_UNKNOWN')
        return value
    if kind=='COUNT':
        cap=policy.get('count_request_microusd_upper')
        if type(cap) is not int or cap<0:raise PermissionError('COUNT_COST_UNKNOWN')
        return cap
    tokens=request['body'].get('generationConfig',{}).get('maxOutputTokens')
    if type(tokens) is not int or not 1<=tokens<=binding['max_output_tokens']:raise PermissionError('OUTPUT_CAP_NOT_BOUND')
    inclusion=policy.get('output_cap_includes_thinking')
    if inclusion is True:billable_output=tokens
    elif inclusion is False:
        thinking=policy.get('thinking_tokens_upper')
        if type(thinking) is not int or thinking<0:raise PermissionError('THINKING_COST_UNKNOWN')
        billable_output=tokens+thinking
    else:raise PermissionError('THINKING_COST_UNKNOWN')
    # USD/million tokens multiplied by tokens is already micro-USD. All
    # uncached input is charged at the frozen upper rate; no speculative rebate.
    return int((amount('input_usd_per_million')*measurement['tokens']+
                amount('output_usd_per_million')*billable_output).to_integral_value(rounding=ROUND_CEILING))


def check_reservation(binding,request,kind,measurement,budget):
    required=reservation_bound(binding,request,kind,measurement)
    configured=budget.config.get('reservation_microusd',{}).get(kind)
    if type(configured) is not int or configured<max(1,required):raise PermissionError('RESERVATION_BELOW_REQUEST_BOUND')
    return required
