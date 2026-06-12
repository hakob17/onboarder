package com.acme.orders;

import org.springframework.cloud.openfeign.FeignClient;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestBody;

@FeignClient(name = "billing-service")
public interface BillingClient {
    @PostMapping("/api/charges")
    ChargeResult charge(@RequestBody ChargeRequest request);
}
