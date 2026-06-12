package com.acme.orders;

import org.springframework.stereotype.Service;

@Service
public class SmsNotificationService implements NotificationService {
    public void orderPlaced(Order order) { }
}
