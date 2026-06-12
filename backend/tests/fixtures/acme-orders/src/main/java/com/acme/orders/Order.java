package com.acme.orders;

import jakarta.persistence.Column;
import jakarta.persistence.Entity;
import jakarta.persistence.Id;
import jakarta.persistence.Table;
import java.time.Instant;

@Entity
@Table(name = "orders")
public class Order {
    @Id
    private Long id;

    @Column(name = "customer_id")
    private Long customerId;

    @Column(name = "total_cents")
    private long totalCents;

    private String status;

    @Column(name = "created_at")
    private Instant createdAt;
}
