package com.acme.orders;

import org.springframework.stereotype.Service;

@Service
public class OrderService {
    private final OrderRepository orderRepository;
    private final PricingService pricingService;
    private final NotificationService notificationService;
    private final BillingClient billingClient;

    public OrderService(OrderRepository orderRepository, PricingService pricingService,
                        NotificationService notificationService, BillingClient billingClient) {
        this.orderRepository = orderRepository;
        this.pricingService = pricingService;
        this.notificationService = notificationService;
        this.billingClient = billingClient;
    }

    public Order placeOrder(OrderDraft draft) {
        long total = pricingService.price(draft);
        Order order = new Order();
        billingClient.charge(new ChargeRequest(total));
        Order saved = orderRepository.save(order);
        notificationService.orderPlaced(saved);
        return saved;
    }

    public Order findOrder(Long id) {
        return orderRepository.findById(id).orElseThrow();
    }
}
