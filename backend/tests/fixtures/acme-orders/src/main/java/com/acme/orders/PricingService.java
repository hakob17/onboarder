package com.acme.orders;

import org.springframework.stereotype.Service;

@Service
public class PricingService {
    public long price(OrderDraft draft) {
        if (draft.couponCode != null && draft.totalCents > 5000) {
            return draft.totalCents - 500;
        }
        return draft.totalCents;
    }
}
