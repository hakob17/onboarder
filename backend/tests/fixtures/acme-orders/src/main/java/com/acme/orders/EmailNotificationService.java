package com.acme.orders;

import org.springframework.stereotype.Service;

@Service
public class EmailNotificationService implements NotificationService {
    public void orderPlaced(Order order) { }
}
