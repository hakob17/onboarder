package com.acme.orders;

import org.springframework.web.bind.annotation.*;

@RestController
@RequestMapping("/api/orders")
public class OrderController {
    private final OrderService orderService;

    public OrderController(OrderService orderService) {
        this.orderService = orderService;
    }

    @PostMapping
    public Order create(@RequestBody OrderDraft draft) {
        return orderService.placeOrder(draft);
    }

    @GetMapping("/{id}")
    public Order get(@PathVariable Long id) {
        return orderService.findOrder(id);
    }
}
